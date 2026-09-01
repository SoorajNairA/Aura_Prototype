import QtQuick

Item {
    id: root

    property string auraState: "IDLE"
    property real audioLevel: 0.0
    property color primaryColor: "#00E5FF"
    property color secondaryColor: "#00B7FF"

    readonly property real stateEnergy: {
        if (auraState === "LISTENING") return 0.85
        if (auraState === "THINKING") return 0.68
        if (auraState === "EXECUTING") return 1.0
        if (auraState === "SPEAKING") return Math.max(0.55, audioLevel)
        return 0.24
    }

    width: 360
    height: 360

    Rectangle {
        id: ambientGlow
        anchors.centerIn: parent
        width: parent.width * 0.74
        height: width
        radius: width / 2
        color: root.primaryColor
        opacity: 0.035 + root.stateEnergy * 0.08
        scale: 1.0 + root.stateEnergy * 0.16

        Behavior on opacity { NumberAnimation { duration: 420 } }
        Behavior on scale { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
    }

    Rectangle {
        id: halo
        anchors.centerIn: parent
        width: parent.width * 0.54
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 2
        border.color: root.primaryColor
        opacity: 0.15 + root.stateEnergy * 0.35
        scale: 1.0 + root.audioLevel * 0.08

        SequentialAnimation on scale {
            running: root.auraState === "IDLE"
            loops: Animation.Infinite
            NumberAnimation { to: 1.035; duration: 2200; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1.0; duration: 2200; easing.type: Easing.InOutSine }
        }
    }

    Rectangle {
        id: sphere
        anchors.centerIn: parent
        width: parent.width * 0.42
        height: width
        radius: width / 2
        color: "#071F2A"
        border.width: 1
        border.color: "#7DF9FF"
        opacity: 0.96
        scale: 1.0 + root.stateEnergy * 0.045 + root.audioLevel * 0.055

        gradient: Gradient {
            GradientStop { position: 0.0; color: "#E6FFFF" }
            GradientStop { position: 0.16; color: "#36E8F5" }
            GradientStop { position: 0.48; color: "#087F99" }
            GradientStop { position: 0.78; color: "#073443" }
            GradientStop { position: 1.0; color: "#031014" }
        }

        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutQuad } }

        Rectangle {
            anchors {
                left: parent.left
                top: parent.top
                leftMargin: parent.width * 0.21
                topMargin: parent.height * 0.15
            }
            width: parent.width * 0.21
            height: width * 0.72
            radius: width / 2
            color: "#FFFFFF"
            opacity: 0.28
            rotation: -35
        }
    }

    Rectangle {
        anchors.centerIn: sphere
        width: sphere.width * 0.54
        height: width
        radius: width / 2
        color: "#E6FFFF"
        opacity: 0.08 + root.stateEnergy * 0.13

        SequentialAnimation on opacity {
            running: true
            loops: Animation.Infinite
            NumberAnimation { to: 0.22; duration: 1500; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.08; duration: 1500; easing.type: Easing.InOutSine }
        }
    }
}
