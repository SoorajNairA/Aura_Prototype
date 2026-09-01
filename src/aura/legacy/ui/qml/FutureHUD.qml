import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Controls

Controls.ApplicationWindow {
    id: window
    visible: true
    width: 1440
    height: 900
    minimumWidth: 1080
    minimumHeight: 700
    title: "AURA"
    color: "#05070A"

    property var bridge: auraBridge
    readonly property string auraState: bridge ? bridge.state : "IDLE"
    readonly property real auraLevel: bridge ? bridge.audioLevel : 0.0
    readonly property string auraStatus: bridge ? bridge.status : "READY"

    StartupSequence {
        id: startupSequence
        entries: window.bridge ? window.bridge.startupEntries : []
        ready: window.bridge ? window.bridge.startupReady : false
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 32
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 72

            Text {
                text: "AURA"
                color: "#E6FFFF"
                font.pixelSize: 26
                font.weight: Font.DemiBold
                font.letterSpacing: 4
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                width: 8
                height: 8
                radius: 4
                color: "#00E5FF"
            }

            Text {
                text: window.auraStatus.toUpperCase()
                color: "#7DF9FF"
                font.pixelSize: 11
                font.letterSpacing: 2
            }

            Controls.ComboBox {
                id: modelSelector
                Layout.preferredWidth: 185
                enabled: window.bridge && window.bridge.startupReady && count > 0
                model: window.bridge ? window.bridge.modelOptions : []
                currentIndex: {
                    if (!window.bridge) return -1
                    return model.indexOf(window.bridge.currentModel)
                }
                onActivated: {
                    if (window.bridge && currentText !== window.bridge.currentModel)
                        window.bridge.selectModel(currentText)
                }

                background: Rectangle {
                    color: "#081116"
                    border.width: 1
                    border.color: modelSelector.activeFocus ? "#00E5FF" : "#163039"
                    radius: 4
                }

                contentItem: Text {
                    leftPadding: 10
                    rightPadding: 28
                    text: modelSelector.displayText || "MODEL"
                    color: modelSelector.enabled ? "#B8D4DA" : "#49646D"
                    font.pixelSize: 10
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }

                delegate: Controls.ItemDelegate {
                    width: modelSelector.width
                    text: modelData
                    contentItem: Text {
                        text: parent.text
                        color: "#B8D4DA"
                        font.pixelSize: 10
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        color: parent.highlighted ? "#103A45" : "#081116"
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Rectangle {
                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                }
                height: 1
                color: "#10272E"
            }

            ParticleField {
                anchors.fill: parent
                anchors.margins: 18
                energy: {
                    if (window.auraState === "EXECUTING") return 1.0
                    if (window.auraState === "THINKING") return 0.72
                    return window.auraLevel
                }
                opacity: 0.8
            }

            StatusPanel {
                anchors {
                    left: parent.left
                    top: parent.top
                    leftMargin: 8
                    topMargin: 42
                }
                width: Math.max(190, Math.min(230, parent.width * 0.18))
                height: 210
                statuses: window.bridge ? window.bridge.systemStatus : []
            }

            ExecutionFeed {
                anchors {
                    right: parent.right
                    top: parent.top
                    bottom: parent.bottom
                    topMargin: 42
                    bottomMargin: 90
                }
                width: Math.max(250, Math.min(330, parent.width * 0.24))
                entries: window.bridge ? window.bridge.executionEntries : []
            }

            MemoryCards {
                anchors {
                    left: parent.left
                    bottom: parent.bottom
                    leftMargin: 8
                    bottomMargin: 20
                }
                width: Math.max(220, Math.min(390, parent.width * 0.24))
                height: 165
                projects: window.bridge ? window.bridge.projectEntries : []
            }

            Item {
                id: coreAssembly
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -58
                width: Math.min(parent.width, parent.height) * 0.56
                height: width

                RotatingRing {
                    anchors.centerIn: parent
                    width: parent.width
                    height: width
                    segmentCount: 32
                    segmentLength: 18
                    speed: window.auraState === "THINKING" ? 6500 : 21000
                    direction: 1
                    energy: window.auraLevel
                    ringOpacity: 0.42
                }

                RotatingRing {
                    anchors.centerIn: parent
                    width: parent.width * 0.79
                    height: width
                    segmentCount: 20
                    segmentLength: 12
                    speed: window.auraState === "THINKING" ? 5100 : 16000
                    direction: -1
                    energy: window.auraLevel
                    ringColor: "#00B7FF"
                    ringOpacity: 0.34
                }

                RotatingRing {
                    anchors.centerIn: parent
                    width: parent.width * 0.61
                    height: width
                    segmentCount: 16
                    segmentLength: 8
                    speed: 12000
                    direction: 1
                    energy: Math.max(
                        window.auraLevel,
                        window.auraState === "SPEAKING" ? 0.7 : 0.1
                    )
                    ringColor: "#7DF9FF"
                    ringOpacity: 0.55
                }
            }

            AIOrb {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -58
                width: Math.min(parent.width, parent.height) * 0.47
                height: width
                auraState: window.auraState
                audioLevel: window.auraLevel
            }

            Waveform {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: Math.min(parent.width, parent.height) * 0.12
                width: Math.min(480, parent.width * 0.42)
                level: window.auraLevel
                active: window.auraState === "LISTENING" ||
                    window.auraState === "SPEAKING"
                opacity: active ? 1.0 : 0.35

                Behavior on opacity { NumberAnimation { duration: 320 } }
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: Math.min(parent.width, parent.height) * 0.14
                spacing: 14

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: window.auraState
                    color: "#7DF9FF"
                    font.pixelSize: 12
                    font.letterSpacing: 4
                }

                Controls.Button {
                    id: listenButton
                    width: 142
                    height: 42
                    text: window.auraState === "LISTENING" ? "LISTENING" : "TALK"
                    onClicked: if (window.bridge) window.bridge.listen()

                    background: Rectangle {
                        color: listenButton.down ? "#103A45" : "#081D24"
                        border.color: "#00E5FF"
                        border.width: 1
                        radius: 4
                    }

                    contentItem: Text {
                        text: listenButton.text
                        color: "#E6FFFF"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font.pixelSize: 11
                        font.letterSpacing: 2
                    }
                }
            }

            Item {
                id: transcriptPanel
                anchors {
                    horizontalCenter: parent.horizontalCenter
                    bottom: parent.bottom
                    bottomMargin: 20
                }
                width: Math.max(420, Math.min(620, parent.width * 0.46))
                height: 168

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8

                    ListView {
                        id: transcriptList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: window.bridge ? window.bridge.transcriptEntries : []
                        spacing: 7
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        onCountChanged: positionViewAtEnd()

                        delegate: Item {
                            required property var modelData
                            width: transcriptList.width
                            height: message.implicitHeight + 4

                            Text {
                                id: message
                                width: Math.min(parent.width * 0.82, implicitWidth)
                                anchors {
                                    left: modelData.role === "assistant" ? parent.left : undefined
                                    right: modelData.role === "user" ? parent.right : undefined
                                }
                                text: modelData.message
                                color: modelData.role === "user" ? "#7DF9FF" : "#B8D4DA"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                horizontalAlignment: modelData.role === "user" ?
                                    Text.AlignRight : Text.AlignLeft

                                NumberAnimation on opacity {
                                    from: 0
                                    to: 1
                                    duration: 260
                                    running: true
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Controls.TextField {
                            id: commandInput
                            Layout.fillWidth: true
                            height: 38
                            placeholderText: "Type an objective"
                            color: "#D7F3F6"
                            placeholderTextColor: "#49646D"
                            font.pixelSize: 11
                            leftPadding: 12
                            rightPadding: 12
                            onAccepted: {
                                if (text.trim() && window.bridge) {
                                    window.bridge.submitText(text)
                                    clear()
                                }
                            }

                            background: Rectangle {
                                color: "#081116"
                                border.width: 1
                                border.color: commandInput.activeFocus ? "#00B7FF" : "#163039"
                                radius: 4
                            }
                        }

                        Controls.Button {
                            id: sendButton
                            width: 38
                            height: 38
                            text: ">"
                            onClicked: commandInput.accepted()

                            background: Rectangle {
                                color: sendButton.down ? "#103A45" : "#081D24"
                                border.width: 1
                                border.color: "#00E5FF"
                                radius: 4
                            }

                            contentItem: Text {
                                text: sendButton.text
                                color: "#E6FFFF"
                                font.pixelSize: 16
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }
        }
    }
}
