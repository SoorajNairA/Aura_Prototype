import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property var statuses: []

    implicitWidth: 210
    implicitHeight: 210

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        Text {
            text: "SYSTEM"
            color: "#E6FFFF"
            font.pixelSize: 11
            font.letterSpacing: 2
        }

        Repeater {
            model: root.statuses

            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 9

                Rectangle {
                    width: 5
                    height: 5
                    radius: 3
                    color: modelData.ok === "true" ? "#00E5FF" : "#FFB347"
                }

                Text {
                    text: modelData.name
                    color: "#58737A"
                    font.pixelSize: 9
                    Layout.preferredWidth: 54
                }

                Text {
                    Layout.fillWidth: true
                    text: modelData.value
                    color: "#B8D4DA"
                    font.pixelSize: 9
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                }
            }
        }
    }
}
