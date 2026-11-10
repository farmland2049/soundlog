import Foundation

/// Detection helper for mock engine backend.
public enum SoundlogMockConfiguration {
    public static func isMockEnabled(parameters: [String: String] = [:]) -> Bool {
        if let env = ProcessInfo.processInfo.environment["SOUNDLOG_MOCK_ENGINES"]?.lowercased(),
           env == "1" || env == "true" || env == "yes" {
            return true
        }
        if let param = parameters["engines"]?.lowercased(), param == "mock" {
            return true
        }
        if let mockParam = parameters["mock"]?.lowercased(),
           mockParam == "1" || mockParam == "true" || mockParam == "yes" {
            return true
        }
        return false
    }
}

/// A mock transcription engine that reads actual audio duration and produces mock text.
public struct MockTranscriptionEngine: TranscriptionEngine {
    public let identifier: String
    public let localeIdentifier: String

    public init(localeIdentifier: String = "zh-CN", identifier: String = "apple-speech-analyzer-mock") {
        self.localeIdentifier = localeIdentifier
        self.identifier = identifier
    }

    public func transcribe(file: URL) async throws -> EngineResult {
        let durationInfo = try UnifiedOutput.audioDuration(file: file)
        guard let duration = durationInfo.seconds, duration > 0 else {
            throw TranscriptionError.io("Mock 转写引擎校验失败: 无法解析音频有效时长 (\(durationInfo.error ?? "无效或损坏的音频"))")
        }
        let segmentDuration = min(duration, 5.0)
        var segments: [TranscriptSegment] = []
        var offset: Double = 0
        while offset < duration {
            let next = min(offset + segmentDuration, duration)
            segments.append(TranscriptSegment(start: offset, end: next, text: "（Mock 转写内容）"))
            offset = next
        }
        let coveredRanges = [try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: duration)]
        return EngineResult(segments: segments, coveredRanges: coveredRanges)
    }
}

/// A mock sound event engine that reads actual audio duration and produces mock classification windows.
public struct MockSoundEventEngine: SoundEventEngine {
    public let identifier: String

    public init(identifier: String = "apple-sound-analysis-mock") {
        self.identifier = identifier
    }

    public func classify(file: URL) async throws -> SoundEventEngineResult {
        let durationInfo = try UnifiedOutput.audioDuration(file: file)
        guard let duration = durationInfo.seconds, duration > 0 else {
            throw TranscriptionError.io("Mock 声音事件引擎校验失败: 无法解析音频有效时长 (\(durationInfo.error ?? "无效或损坏的音频"))")
        }
        var windows: [SoundClassificationWindow] = []
        let windowStep = 1.0
        var offset: Double = 0
        while offset < duration {
            let next = min(offset + windowStep, duration)
            let candidates = [
                SoundEventCandidate(category: "speech", confidence: 0.9),
                SoundEventCandidate(category: "silence", confidence: 0.1)
            ]
            windows.append(SoundClassificationWindow(start: offset, end: next, candidates: candidates, classificationStatus: "classified"))
            offset = next
        }
        return SoundEventEngineResult(windows: windows)
    }
}

/// A mock speaker diarization engine that reads actual audio duration and produces mock speaker segments.
public struct MockSpeakerDiarizationEngine: SpeakerDiarizationEngine {
    public let identifier: String

    public init(identifier: String = "FluidAudio.OfflineVBx-mock@0.17.7") {
        self.identifier = identifier
    }

    public func diarize(file: URL) async throws -> SpeakerEngineResult {
        let durationInfo = try UnifiedOutput.audioDuration(file: file)
        guard let duration = durationInfo.seconds, duration > 0 else {
            throw TranscriptionError.io("Mock 说话人分离引擎校验失败: 无法解析音频有效时长 (\(durationInfo.error ?? "无效或损坏的音频"))")
        }
        let segments = [
            SpeakerSegment(speakerID: "SPEAKER_00", startOffsetSeconds: 0, endOffsetSeconds: duration)
        ]
        return SpeakerEngineResult(segments: segments)
    }
}
