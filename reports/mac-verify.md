# Soundlog 合成验证报告

- 时间：2026-11-10T07:48:21+08:00
- 系统：Linux-6.12.113+-x86_64-with-glibc2.41
- Swift：Swift version 6.1.2 (swift-6.1.2-RELEASE) Target: x86_64-unknown-linux-gnu
- swift build：通过（退出码 0）
- swift test：通过（54 项测试；退出码 0）
- 合成 WAV process：退出码 1（Linux Apple 模块 unsupported 属预期状态）

## 模块状态

| 模块 | 状态 | 原因 |
|---|---|---|
| inputCoverage | incomplete | 覆盖存在缺口或无转写覆盖 |
| runManifest | completed |  |
| soundEvents | unsupported | SoundAnalysis/AVFoundation 不可用 |
| speakerAlignment | skipped | 转写或说话人分离未完成 |
| speakerDiarization | unsupported | FluidAudio 仅支持 macOS |
| transcription | unsupported | Speech/AVFoundation 不可用 |
| unifiedTranscript | skipped | 没有可用候选对齐结果 |

合成输入为 1 秒静音 WAV；未使用真实录音、身份样本或模型。模型缺失时应在对应 Mac 模块状态中记录原因。
