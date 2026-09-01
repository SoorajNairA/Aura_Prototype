import QtQuick

Rectangle {
    id: root

    property bool running: true
    property bool ready: false
    property var entries: []
    signal finished()

    anchors.fill: parent
    color: "#05070A"
    opacity: running ? 1 : 0
    visible: opacity > 0
    z: 100

    Behavior on opacity {
        NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
    }

    Column {
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 80)
        spacing: 18

        Text {
            id: logo
            anchors.horizontalCenter: parent.horizontalCenter
            text: "AURA"
            color: "#E6FFFF"
            font.pixelSize: 38
            font.weight: Font.DemiBold
            font.letterSpacing: 8
            opacity: 0
            scale: 0.92
        }

        Rectangle {
            id: ignitionLine
            anchors.horizontalCenter: parent.horizontalCenter
            width: 0
            height: 1
            color: "#00E5FF"
            opacity: 0.8
        }

        Column {
            width: parent.width
            spacing: 8

            Repeater {
                model: root.entries

                Row {
                    required property var modelData
                    width: parent.width
                    spacing: 10

                    Text {
                        width: 14
                        text: {
                            if (modelData.status === "error") return "!"
                            if (modelData.status === "warning") return "!"
                            if (modelData.status === "active") return ">"
                            return "+"
                        }
                        color: modelData.status === "error" ? "#FF6B6B" :
                            modelData.status === "warning" ? "#FFB347" : "#00E5FF"
                        font.pixelSize: 10
                    }

                    Text {
                        width: parent.width - 24
                        text: modelData.label
                        color: modelData.status === "error" ? "#FF9B9B" :
                            modelData.status === "warning" ? "#FFCF85" : "#7DF9FF"
                        font.pixelSize: 10
                        font.letterSpacing: 1
                        elide: Text.ElideRight

                        NumberAnimation on opacity {
                            from: 0
                            to: 1
                            duration: 180
                            running: true
                        }
                    }
                }
            }
        }

        Text {
            id: onlineLabel
            anchors.horizontalCenter: parent.horizontalCenter
            text: "AURA ONLINE"
            color: "#00E5FF"
            font.pixelSize: 12
            font.letterSpacing: 4
            opacity: 0
        }
    }

    SequentialAnimation {
        running: true

        ParallelAnimation {
            NumberAnimation {
                target: logo
                property: "opacity"
                from: 0
                to: 1
                duration: 420
            }
            NumberAnimation {
                target: logo
                property: "scale"
                from: 0.92
                to: 1
                duration: 520
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                target: ignitionLine
                property: "width"
                from: 0
                to: 210
                duration: 520
                easing.type: Easing.OutCubic
            }
        }
    }

    SequentialAnimation {
        id: completionSequence
        running: root.ready

        PauseAnimation { duration: 300 }
        NumberAnimation {
            target: onlineLabel
            property: "opacity"
            from: 0
            to: 1
            duration: 260
        }
        PauseAnimation { duration: 520 }
        ScriptAction {
            script: {
                root.running = false
                root.finished()
            }
        }
    }
}
