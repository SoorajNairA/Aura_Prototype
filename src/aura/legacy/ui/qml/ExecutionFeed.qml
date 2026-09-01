import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property var entries: []
    property color accentColor: "#00E5FF"

    implicitWidth: 300
    implicitHeight: 440

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Rectangle {
                width: 5
                height: 5
                radius: 3
                color: root.accentColor
            }

            Text {
                text: "EXECUTION"
                color: "#E6FFFF"
                font.pixelSize: 11
                font.letterSpacing: 2
            }

            Item { Layout.fillWidth: true }

            Text {
                text: root.entries.length.toString().padStart(2, "0")
                color: "#52707A"
                font.pixelSize: 10
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: "#163039"
        }

        ListView {
            id: feed
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: root.entries
            spacing: 13
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            verticalLayoutDirection: ListView.TopToBottom

            onCountChanged: positionViewAtEnd()

            delegate: Item {
                required property var modelData
                width: feed.width
                height: messageText.implicitHeight + 8
                opacity: 0

                NumberAnimation on opacity {
                    from: 0
                    to: 1
                    duration: 320
                    running: true
                }

                Row {
                    anchors.fill: parent
                    spacing: 10

                    Text {
                        text: modelData.time
                        color: "#49646D"
                        font.pixelSize: 9
                        font.family: "Consolas"
                    }

                    Text {
                        id: messageText
                        width: parent.width - 78
                        text: modelData.message
                        color: "#B8D4DA"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: feed.count === 0
                text: "NO ACTIVE OPERATIONS"
                color: "#38515A"
                font.pixelSize: 9
                font.letterSpacing: 1
            }
        }
    }
}
