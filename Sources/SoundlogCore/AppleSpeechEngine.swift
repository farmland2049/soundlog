#if canImport(Speech) && canImport(AVFoundation)
import Foundation
import Speech
import AVFoundation

/// Uses Apple's SpeechAnalyzer/SpeechTranscriber APIs. Not compiled or verified on Mac yet.
public struct AppleSpeechEngine: TranscriptionEngine {
    public let identifier = "apple-speech-analyzer"
    public let localeIdentifier: String
    public init(localeIdentifier: String = "zh-CN") { self.localeIdentifier = localeIdentifier }

    public func transcribe(file: URL) async throws -> EngineResult {
        let transcriber = SpeechTranscriber(locale: Locale(identifier: localeIdentifier), preset: .transcription)
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let audioFile = try AVAudioFile(forReading: file)
        let duration = Double(audioFile.length) / audioFile.processingFormat.sampleRate
        let results = transcriber.results
        let task = Task { () throws -> [TranscriptSegment] in
            var segments: [TranscriptSegment] = []
            for try await result in results {
                let text = String(result.text.characters)
                let range = result.range
                segments.append(TranscriptSegment(start: range.start.seconds, end: range.end.seconds, text: text))
            }
            return segments
        }
        try await analyzer.start(inputAudioFile: audioFile, finishAfterFile: true)
        let segments = try await task.value
        let covered = try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: duration)
        return EngineResult(segments: segments, coveredRanges: [covered])
    }
}
#endif
