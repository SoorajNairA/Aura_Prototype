import QtQuick

Item {
    id: root

    property real energy: 0.0
    property color particleColor: "#00B7FF"
    property bool running: true

    function pseudo(index, salt) {
        return Math.abs(Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453) % 1
    }

    component OrbitLayer: Item {
        id: layer

        property int particleCount: 48
        property real innerRadius: 0.22
        property real outerRadius: 0.48
        property int rotationDuration: 42000
        property int direction: 1
        property real phaseOffset: 0

        anchors.fill: parent

        Repeater {
            model: layer.particleCount

            Rectangle {
                required property int index

                readonly property real seed: root.pseudo(index, layer.phaseOffset + 1)
                readonly property real angle: (
                    index / layer.particleCount * Math.PI * 2 +
                    layer.phaseOffset
                )
                readonly property real orbit: root.width * (
                    layer.innerRadius +
                    seed * (layer.outerRadius - layer.innerRadius)
                )

                x: root.width / 2 + Math.cos(angle) * orbit - width / 2
                y: root.height / 2 + Math.sin(angle) * orbit - height / 2
                width: 1.2 + root.pseudo(index, layer.phaseOffset + 3) * 2.1
                height: width
                radius: width / 2
                color: root.particleColor
                opacity: 0.08 + seed * 0.34 + root.energy * 0.16
                antialiasing: true
            }
        }

        RotationAnimator on rotation {
            from: layer.direction > 0 ? 0 : 360
            to: layer.direction > 0 ? 360 : 0
            duration: Math.max(9000, layer.rotationDuration - root.energy * 18000)
            loops: Animation.Infinite
            running: root.running
        }
    }

    OrbitLayer {
        particleCount: 44
        innerRadius: 0.18
        outerRadius: 0.32
        rotationDuration: 32000
        direction: 1
        phaseOffset: 0.4
    }

    OrbitLayer {
        particleCount: 56
        innerRadius: 0.31
        outerRadius: 0.43
        rotationDuration: 48000
        direction: -1
        phaseOffset: 1.7
    }

    OrbitLayer {
        particleCount: 64
        innerRadius: 0.42
        outerRadius: 0.52
        rotationDuration: 61000
        direction: 1
        phaseOffset: 3.1
    }
}
