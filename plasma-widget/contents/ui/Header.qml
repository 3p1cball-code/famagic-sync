import QtQuick

/*
 * Widget header in the regenradar look: letterspaced caps on the left
 * (title + dim subtitle), a thin large value on the right with a small
 * caption underneath, optionally led by a status dot.
 *
 * Shared between famagic and deebot-map (regenradar draws the original
 * inline in RadarView.qml) - keep the copies equal.
 */
Item {
    id: h

    property real ui: 1.0
    property color ink: "#ffffff"

    property string title: ""
    property string subtitle: ""
    property string value: ""
    property color valueColor: ink
    property string caption: ""
    property color captionColor: ink
    property real captionOpacity: 0.45
    property color dotColor: "transparent"

    implicitHeight: Math.max(left.y + left.implicitHeight, right.y + right.implicitHeight)
                    + Math.round(8 * ui)

    Column {
        id: left
        anchors { left: parent.left; top: parent.top
                  leftMargin: Math.round(13 * h.ui); topMargin: Math.round(11 * h.ui) }
        width: parent.width - right.width - Math.round(30 * h.ui)
        spacing: 2

        Text {
            width: parent.width
            text: h.title.toUpperCase()
            color: h.ink
            opacity: 0.6
            elide: Text.ElideRight
            font.pixelSize: Math.round(9.5 * h.ui)
            font.letterSpacing: 3.2
            font.weight: Font.Medium
        }
        Text {
            width: parent.width
            text: h.subtitle.toUpperCase()
            visible: text.length > 0
            color: h.ink
            opacity: 0.3
            elide: Text.ElideRight
            font.pixelSize: Math.round(7 * h.ui)
            font.letterSpacing: 1.6
        }
    }

    Column {
        id: right
        anchors { right: parent.right; top: parent.top
                  rightMargin: Math.round(13 * h.ui); topMargin: Math.round(8 * h.ui) }
        spacing: 0

        Text {
            anchors.right: parent.right
            text: h.value.toUpperCase()
            visible: text.length > 0
            color: h.valueColor
            opacity: 0.95
            font.pixelSize: Math.round(23 * h.ui)
            font.weight: Font.Thin
        }
        Row {
            anchors.right: parent.right
            spacing: Math.round(5 * h.ui)
            visible: h.caption.length > 0

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                visible: h.dotColor.a > 0
                width: Math.round(4 * h.ui)
                height: width
                radius: width / 2
                color: h.dotColor
            }
            Text {
                text: h.caption.toUpperCase()
                color: h.captionColor
                opacity: h.captionOpacity
                font.pixelSize: Math.round(7.5 * h.ui)
                font.letterSpacing: 1.4
                font.weight: Font.Medium
            }
        }
    }
}
