import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property var projects: []

    implicitWidth: 300
    implicitHeight: 220

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true

            Text {
                text: "MEMORY"
                color: "#E6FFFF"
                font.pixelSize: 11
                font.letterSpacing: 2
            }

            Item { Layout.fillWidth: true }

            Text {
                text: root.projects.length + " PROJECTS"
                color: "#49646D"
                font.pixelSize: 9
            }
        }

        ListView {
            id: cards
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: ListView.Horizontal
            spacing: 10
            clip: true
            model: root.projects
            boundsBehavior: Flickable.StopAtBounds

            delegate: Rectangle {
                required property var modelData

                width: 166
                height: 104
                radius: 6
                color: "#0A1217"
                border.width: 1
                border.color: "#17333C"
                opacity: 0

                NumberAnimation on opacity {
                    from: 0
                    to: 0.92
                    duration: 360
                    running: true
                }

                Column {
                    anchors {
                        fill: parent
                        margins: 14
                    }
                    spacing: 11

                    Rectangle {
                        width: 20
                        height: 2
                        color: "#00E5FF"
                    }

                    Text {
                        width: parent.width
                        text: modelData.name
                        color: "#D7F3F6"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                        elide: Text.ElideRight
                    }

                    Text {
                        width: parent.width
                        text: modelData.status
                        color: "#5F7D84"
                        font.pixelSize: 9
                        elide: Text.ElideRight
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: cards.count === 0
                text: "MEMORY READY"
                color: "#38515A"
                font.pixelSize: 9
                font.letterSpacing: 1
            }
        }
    }
}
