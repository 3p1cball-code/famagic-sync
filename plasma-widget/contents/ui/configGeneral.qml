import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    id: page

    property alias cfg_rangeMode: rangeCombo.currentIndex
    property string cfg_filterMember: "*"
    property string cfg_listIds: ""
    property var listModel: []
    property var memberModel: [
        { text: "Alle", value: "*" },
        { text: "Niemand", value: "none" }
    ]

    function fetchMembers() {
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return;
            if (xhr.status !== 200)
                return;
            try {
                var snap = JSON.parse(xhr.responseText);
                var m = [
                    { text: "Alle", value: "*" },
                    { text: "Niemand", value: "none" }
                ];
                (snap.members || []).forEach(function(mem) {
                    var p = mem.profile || {};
                    m.push({ text: p.first_name || mem.first_name || mem.role || "?", value: mem.id });
                });
                page.memberModel = m;
                page.syncPerson();
                page.listModel = (snap.lists || []).filter(function(l) {
                    return !l.archived_at;
                });
            } catch (e) {
            }
        };
        xhr.open("GET", "http://192.168.33.24:8791/api/snapshot");
        xhr.setRequestHeader("Accept", "application/json");
        xhr.send();
    }

    function isListChecked(id) {
        var s = page.cfg_listIds;
        if (s === "" || s === "*")
            return true;
        if (s === "-")
            return false;
        return s.split(",").indexOf(id) >= 0;
    }

    function toggleList(id, checked) {
        var all = page.listModel.map(function(l) { return l.id; });
        var s = page.cfg_listIds;
        var sel;
        if (s === "" || s === "*")
            sel = all.slice();
        else if (s === "-")
            sel = [];
        else
            sel = s.split(",");
        if (checked) {
            if (sel.indexOf(id) < 0)
                sel.push(id);
        } else {
            sel = sel.filter(function(x) { return x !== id; });
        }
        if (sel.length === all.length)
            page.cfg_listIds = "";
        else if (sel.length === 0)
            page.cfg_listIds = "-";
        else
            page.cfg_listIds = sel.join(",");
    }

    function syncPerson() {
        for (var i = 0; i < page.memberModel.length; i++) {
            if (page.memberModel[i].value === page.cfg_filterMember) {
                personCombo.currentIndex = i;
                return;
            }
        }
        personCombo.currentIndex = 0;
    }

    Kirigami.FormLayout {
        anchors.left: parent.left
        anchors.right: parent.right

        QQC2.ComboBox {
            id: rangeCombo
            Kirigami.FormData.label: i18n("Zeitraum:")
            model: [ "Diese Woche", "Heute", "7 Tage", "14 Tage", "30 Tage", "Alle" ]
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
        }

        Item { Kirigami.FormData.isSection: true; Kirigami.FormData.label: i18n("Listen") }
        ColumnLayout {
            Repeater {
                model: page.listModel
                delegate: QQC2.CheckBox {
                    text: modelData.title
                    checked: page.isListChecked(modelData.id)
                    onToggled: page.toggleList(modelData.id, checked)
                }
            }
        }

        QQC2.ComboBox {
            id: personCombo
            Kirigami.FormData.label: i18n("Person:")
            model: page.memberModel
            textRole: "text"
            valueRole: "value"
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
            Component.onCompleted: {
                page.fetchMembers();
                page.syncPerson();
            }
            onActivated: page.cfg_filterMember = page.memberModel[currentIndex].value
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
            wrapMode: Text.WordWrap
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            text: i18n("Das Widget zeigt offene Aufgaben (auch überfällige) bis zum Ende des Zeitraums, nur aus den angehakten Listen. Klick auf einen Eintrag öffnet die Famagic-App.")
        }
    }
}
