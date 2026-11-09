import Foundation

/// An anonymous speaker interval measured from the original recording.
/// `speakerID` is local to this recording; it is not a person's identity.
public struct SpeakerSegment: Codable, Equatable, Sendable {
    public let speakerID: String?
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double

    public init(speakerID: String?, startOffsetSeconds: Double, endOffsetSeconds: Double) {
        self.speakerID = speakerID
        self.startOffsetSeconds = startOffsetSeconds
        self.endOffsetSeconds = endOffsetSeconds
    }
}

public struct SpeakerTimelineDocument: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let sourcePath: String
    public let sourceSHA256: String
    public let recordingStartLocal: String
    public let engine: String
    public let segments: [SpeakerTimelineEntry]
    public let accuracyAssessment: String
}

public struct SpeakerTimelineEntry: Codable, Equatable, Sendable {
    public let speakerID: String?
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double
    public let absoluteStartLocal: String
    public let absoluteEndLocal: String
}

public struct SpeakerEngineResult: Sendable {
    public let segments: [SpeakerSegment]
    public init(segments: [SpeakerSegment]) { self.segments = segments }
}

public protocol SpeakerDiarizationEngine: Sendable {
    var identifier: String { get }
    func diarize(file: URL) async throws -> SpeakerEngineResult
}

public struct SpeakerTimelinePipeline: Sendable {
    public let engine: any SpeakerDiarizationEngine

    public init(engine: any SpeakerDiarizationEngine) { self.engine = engine }

    public func run(file: URL, runDirectory: URL) async throws -> SpeakerTimelineDocument {
        let recordingStart: RecordingStart
        do {
            recordingStart = try RecordingStart(filename: file.lastPathComponent)
        } catch {
            throw TranscriptionError.invalidStartTime(file.lastPathComponent)
        }

        let result = try await engine.diarize(file: file)
        var entries: [SpeakerTimelineEntry] = []
        for segment in result.segments {
            let range = try AudioTimeRange(
                startOffsetSeconds: segment.startOffsetSeconds,
                endOffsetSeconds: segment.endOffsetSeconds
            )
            entries.append(SpeakerTimelineEntry(
                speakerID: segment.speakerID,
                startOffsetSeconds: range.startOffsetSeconds,
                endOffsetSeconds: range.endOffsetSeconds,
                absoluteStartLocal: try recordingStart.timestamp(atOffsetSeconds: range.startOffsetSeconds),
                absoluteEndLocal: try recordingStart.timestamp(atOffsetSeconds: range.endOffsetSeconds)
            ))
        }
        try validateChronological(entries)

        let document = SpeakerTimelineDocument(
            schemaVersion: 1,
            sourcePath: file.path,
            sourceSHA256: try SHA256.file(file),
            recordingStartLocal: try recordingStart.timestamp(atOffsetSeconds: 0),
            engine: engine.identifier,
            segments: entries,
            accuracyAssessment: "not_evaluated"
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try AtomicFile.write(
            try encoder.encode(document),
            to: runDirectory.appendingPathComponent("speaker-timeline.json")
        )
        return document
    }

    private func validateChronological(_ entries: [SpeakerTimelineEntry]) throws {
        for pair in zip(entries, entries.dropFirst())
        where pair.1.startOffsetSeconds < pair.0.startOffsetSeconds {
            throw TimelineError.outOfOrderRanges
        }
    }
}
