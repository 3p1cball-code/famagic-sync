import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami
import QtQuick.Controls as QQC2
import QtQuick.Effects

PlasmoidItem {
    id: root

    Plasmoid.backgroundHints: Plasmoid.configuration.backgroundBlur ? PlasmaCore.Types.NoBackground : PlasmaCore.Types.TranslucentBackground

    property var snap: null
    property var tasks: []
    property var memberList: []
    property bool vegaError: false
    property bool cloudOffline: false
    property int pending: 0
    readonly property string serverUrl: "http://192.168.33.24:8791"
    readonly property var rangeLabels: [ "Diese Woche", "Heute", "7 Tage", "14 Tage", "30 Tage", "Alle" ]
    readonly property string accent: "#e8a13a"
    readonly property string green: "#7fae6f"
    readonly property string red: "#d96a5a"

    preferredRepresentation: fullRepresentation

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: function(source, data) {
            disconnectSource(source);
        }
        function openFamagic() {
            connectSource("__FAMAGIC_OPEN__");
        }
    }

    function openApp() {
        executable.openFamagic();
    }

    function iso(d) {
        var y = d.getFullYear();
        var m = ("0" + (d.getMonth() + 1)).slice(-2);
        var dd = ("0" + d.getDate()).slice(-2);
        return y + "-" + m + "-" + dd;
    }

    function rangeEnd() {
        var mode = Plasmoid.configuration.rangeMode;
        var d = new Date();
        d.setHours(0, 0, 0, 0);
        if (mode === 1)
            return iso(d);
        if (mode === 2)
            d.setDate(d.getDate() + 6);
        else if (mode === 3)
            d.setDate(d.getDate() + 13);
        else if (mode === 4)
            d.setDate(d.getDate() + 29);
        else if (mode === 0)
            d.setDate(d.getDate() + (6 - ((d.getDay() + 6) % 7)));
        else
            return null;
        return iso(d);
    }

    function dueText(t) {
        if (!t.due_date)
            return "";
        var parts = t.due_date.split("-").map(Number);
        var due = new Date(parts[0], parts[1] - 1, parts[2]);
        var now = new Date();
        now.setHours(0, 0, 0, 0);
        var diff = Math.round((due - now) / 86400000);
        if (diff === 0) return "heute";
        if (diff === 1) return "morgen";
        if (diff < 0) return (-diff) + " T. überfällig";
        return ("0" + due.getDate()).slice(-2) + "-" + ("0" + (due.getMonth() + 1)).slice(-2) + "-" + due.getFullYear();
    }

    function overdue(t) {
        return t.due_date && t.due_date < iso(new Date());
    }

    function memberName(id) {
        if (id === "*") return "Alle";
        if (id === "none") return "Niemand";
        for (var i = 0; i < memberList.length; i++) {
            var m = memberList[i];
            var p = m.profile || {};
            if (m.id === id)
                return p.first_name || m.first_name || m.role || "?";
        }
        return id;
    }

    function applyFilter() {
        if (!snap) {
            tasks = [];
            return;
        }
        var end = rangeEnd();
        var mode = Plasmoid.configuration.rangeMode;
        var member = Plasmoid.configuration.filterMember;
        var active = {};
        (snap.lists || []).forEach(function(l) {
            if (!l.archived_at)
                active[l.id] = true;
        });
        var setting = Plasmoid.configuration.listIds || "";
        var allowed = {};
        if (setting === "-") {
        } else if (setting === "" || setting === "*") {
            allowed = active;
        } else {
            setting.split(",").forEach(function(id) {
                if (active[id])
                    allowed[id] = true;
            });
        }
        var privateLists = {};
        (snap.lists || []).forEach(function(l) {
            if (l.is_private)
                privateLists[l.id] = true;
        });
        var out = [];
        (snap.tasks || []).forEach(function(t) {
            if (t.is_completed || t.parent_task_id)
                return;
            if (!allowed[t.list_id])
                return;
            var ids = t.assignee_member_ids || [];
            if (!privateLists[t.list_id]) {
                if (member === "none" && ids.length)
                    return;
                if (member !== "*" && member !== "none" && ids.indexOf(member) < 0)
                    return;
            }
            if (t.due_date) {
                if (end && t.due_date > end)
                    return;
            } else if (mode !== 5) {
                return;
            }
            out.push(t);
        });
        out.sort(function(a, b) {
            var ad = a.due_date || "9999-12-31";
            var bd = b.due_date || "9999-12-31";
            if (ad !== bd) return ad < bd ? -1 : 1;
            return (a.title || "").toLowerCase() < (b.title || "").toLowerCase() ? -1 : 1;
        });
        tasks = out.slice(0, 8);
    }

    function fetchData() {
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return;
            if (xhr.status === 200) {
                try {
                    snap = JSON.parse(xhr.responseText);
                    vegaError = false;
                    cloudOffline = !!snap.offline;
                    pending = snap.pending || 0;
                    memberList = snap.members || [];
                    applyFilter();
                } catch (e) {
                    vegaError = true;
                }
            } else {
                vegaError = true;
            }
        };
        xhr.open("GET", serverUrl + "/api/snapshot");
        xhr.setRequestHeader("Accept", "application/json");
        xhr.send();
    }

    function statusColor() {
        if (vegaError)
            return red;
        if (cloudOffline)
            return accent;
        return green;
    }

    function statusText() {
        if (vegaError)
            return "offline";
        if (cloudOffline)
            return "online" + (pending ? " · " + pending + " warten" : "");
        return "online";
    }

    Timer {
        interval: 30000
        running: true
        repeat: true
        onTriggered: root.fetchData()
    }

    Component.onCompleted: fetchData()

    Connections {
        target: Plasmoid.configuration
        function onRangeModeChanged() { root.applyFilter(); }
        function onFilterMemberChanged() { root.applyFilter(); }
    }

    compactRepresentation: MouseArea {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 6
        Layout.minimumHeight: Kirigami.Units.gridUnit * 2
        onClicked: root.openApp()
        RowLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            Rectangle {
                width: Kirigami.Units.smallSpacing
                height: width
                radius: width / 2
                color: root.statusColor()
            }
            QQC2.Label {
                text: "Famagic"
                font.bold: true
                color: root.accent
            }
            QQC2.Label {
                text: root.tasks.length ? root.tasks.length : ""
                color: Kirigami.Theme.disabledTextColor
            }
        }
    }

    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 14
        Layout.minimumHeight: Kirigami.Units.gridUnit * 9
        Layout.preferredWidth: Kirigami.Units.gridUnit * 20
        Layout.preferredHeight: Kirigami.Units.gridUnit * 14

        ShaderEffectSource {
            id: wallpaperSource
            width: parent.width
            height: parent.height
            sourceItem: Plasmoid.containment.wallpaperGraphicsObject
            sourceRect: {
                var wgo = Plasmoid.containment.wallpaperGraphicsObject;
                if (!wgo)
                    return Qt.rect(0, 0, 0, 0);
                return Qt.rect(plasmoid.geometry.x - wgo.x, plasmoid.geometry.y - wgo.y, width, height);
            }
            live: false
            visible: false
        }

        MultiEffect {
            anchors.fill: parent
            source: wallpaperSource
            visible: Plasmoid.configuration.backgroundBlur && wallpaperSource.sourceItem !== null
            blurEnabled: true
            blur: Plasmoid.configuration.backgroundBlurStrength
            blurMax: 64
            autoPaddingEnabled: false
        }

        Rectangle {
            anchors.fill: parent
            radius: Kirigami.Units.gridUnit * 0.6
            color: Qt.rgba(0.05, 0.05, 0.08, Plasmoid.configuration.backgroundOpacity)
            visible: Plasmoid.configuration.backgroundOpacity > 0.01
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                QQC2.Label {
                    text: "Famagic"
                    font.bold: true
                    color: root.accent
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: Kirigami.Units.smallSpacing
                    height: width
                    radius: width / 2
                    color: root.statusColor()
                }
                QQC2.Label {
                    text: root.statusText()
                    color: root.statusColor()
                    font: Kirigami.Theme.smallFont
                }
            }

            QQC2.Label {
                Layout.fillWidth: true
                text: root.rangeLabels[Plasmoid.configuration.rangeMode] + " · " + root.memberName(Plasmoid.configuration.filterMember)
                color: Kirigami.Theme.disabledTextColor
                font: Kirigami.Theme.smallFont
                elide: Text.ElideRight
            }

            QQC2.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
                ColumnLayout {
                    width: parent.width
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: root.tasks
                        delegate: Item {
                            Layout.fillWidth: true
                            implicitHeight: row.implicitHeight
                            MouseArea {
                                anchors.fill: parent
                                onClicked: root.openApp()
                            }
                            RowLayout {
                                id: row
                                width: parent.width
                                QQC2.Label {
                                    text: root.dueText(modelData)
                                    color: root.overdue(modelData) ? root.red : root.accent
                                    font: Kirigami.Theme.smallFont
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                                    Layout.alignment: Qt.AlignTop
                                }
                                QQC2.Label {
                                    text: modelData.title || ""
                                    color: Kirigami.Theme.textColor
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }

            QQC2.Label {
                visible: root.tasks.length === 0
                Layout.fillWidth: true
                text: root.vegaError ? "VEGA nicht erreichbar" : (root.snap ? "Keine fälligen Aufgaben" : "Lade …")
                color: root.vegaError ? root.red : Kirigami.Theme.disabledTextColor
                font: Kirigami.Theme.smallFont
            }

            MouseArea {
                Layout.fillWidth: true
                height: openLabel.implicitHeight
                onClicked: root.openApp()
                QQC2.Label {
                    id: openLabel
                    text: "Öffnen"
                    color: root.accent
                    font: Kirigami.Theme.smallFont
                }
            }
        }
    }
}
