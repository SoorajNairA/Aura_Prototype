import QtQuick

Item {
    id: root

    property color ringColor: "#00E5FF"
    property real ringOpacity: 0.45
    property int segmentCount: 24
    property real segmentLength: 16
    property real speed: 18000
    property int direction: 1
    property real energy: 0.0
    property bool running: true

    Repeater {
        model: root.segmentCount

        Rectangle {
            required property int index
            anchors.centerIn: parent
            width: root.segmentLength + root.energy * 8
            height: index % 4 === 0 ? 2 : 1
            radius: 1
            color: root.ringColor
            opacity: root.ringOpacity * (index % 3 === 0 ? 1.0 : 0.52)
            antialiasing: true
            transform: [
                Translate { y: -root.height / 2 + 2 },
                Rotation {
                    origin.x: width / 2
                    origin.y: root.height / 2 - 2
                    angle: index * (360 / root.segmentCount)
                }
            ]
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: width / 2
        color: "transparent"
        border.width: 1
        border.color: root.ringColor
        opacity: root.ringOpacity * 0.22
        antialiasing: true
    }

    RotationAnimator on rotation {
        from: root.direction > 0 ? 0 : 360
        to: root.direction > 0 ? 360 : 0
        duration: Math.max(1800, root.speed - root.energy * root.speed * 0.55)
        loops: Animation.Infinite
        running: root.running
    }
}
