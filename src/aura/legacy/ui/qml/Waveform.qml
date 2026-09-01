import QtQuick

Item {
    id: root

    property real level: 0.0
    property bool active: false
    property color lineColor: "#7DF9FF"
    property real phase: 0.0

    width: 420
    height: 72

    NumberAnimation on phase {
        from: 0
        to: Math.PI * 2
        duration: 1800
        loops: Animation.Infinite
        running: root.active
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()

            const center = height / 2
            const energy = root.active ? Math.max(0.08, root.level) : 0.025
            const amplitude = 3 + energy * height * 0.34
            const points = 72

            ctx.beginPath()
            ctx.lineWidth = 1.5
            ctx.strokeStyle = root.lineColor
            ctx.globalAlpha = 0.78

            for (let index = 0; index <= points; index++) {
                const progress = index / points
                const envelope = Math.pow(Math.sin(progress * Math.PI), 1.6)
                const primary = Math.sin(progress * Math.PI * 6 + root.phase)
                const secondary = Math.sin(progress * Math.PI * 13 - root.phase * 0.7) * 0.28
                const y = center + (primary + secondary) * amplitude * envelope
                const x = progress * width
                if (index === 0) ctx.moveTo(x, y)
                else ctx.lineTo(x, y)
            }
            ctx.stroke()

            ctx.beginPath()
            ctx.lineWidth = 1
            ctx.strokeStyle = "#00B7FF"
            ctx.globalAlpha = 0.2
            for (let index = 0; index <= points; index++) {
                const progress = index / points
                const envelope = Math.sin(progress * Math.PI)
                const y = center + Math.sin(progress * Math.PI * 4 - root.phase) *
                    amplitude * 0.52 * envelope
                const x = progress * width
                if (index === 0) ctx.moveTo(x, y)
                else ctx.lineTo(x, y)
            }
            ctx.stroke()
        }

        Connections {
            target: root
            function onLevelChanged() { canvas.requestPaint() }
            function onPhaseChanged() { canvas.requestPaint() }
            function onActiveChanged() { canvas.requestPaint() }
        }
    }
}
