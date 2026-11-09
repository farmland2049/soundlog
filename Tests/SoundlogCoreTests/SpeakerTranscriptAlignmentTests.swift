import XCTest
@testable import SoundlogCore

final class SpeakerTranscriptAlignmentTests: XCTestCase {
    private func aligned(transcriptHash: String = "sha", speakerHash: String = "sha", transcriptStart: String = "2024-01-01T00:00:00.000", speakerStart: String = "2024-01-01T00:00:00.000", speakers: [SpeakerTimelineEntry]) throws -> SpeakerAlignedTranscriptDocument {
        let raw = RawTranscription(schemaVersion: 1, sourcePath: "synthetic", sourceSHA256: transcriptHash, engine: "fake", parameters: [:], recordingStartLocal: transcriptStart,
                                  segments: [TranscriptSegment(start: 1, end: 3, text: "synthetic words")],
                                  coverage: [.init(try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 4))],
                                  textRanges: [.init(try AudioTimeRange(startOffsetSeconds: 1, endOffsetSeconds: 3))], status: "completed_with_text", accuracyAssessment: "not_evaluated")
        let timeline = SpeakerTimelineDocument(schemaVersion: 1, sourcePath: "synthetic", sourceSHA256: speakerHash, recordingStartLocal: speakerStart, engine: "fake", segments: speakers, accuracyAssessment: "not_evaluated")
        return try SpeakerTranscriptAlignmentPipeline.align(raw: raw, speakers: timeline, file: URL(fileURLWithPath: "/tmp/20240101000000.wav"))
    }
    private func speaker(_ id: String?, _ start: Double, _ end: Double) throws -> SpeakerTimelineEntry {
        SpeakerTimelineEntry(speakerID: id, startOffsetSeconds: start, endOffsetSeconds: end,
                             absoluteStartLocal: "synthetic", absoluteEndLocal: "synthetic")
    }
    func testTemporalOverlapProducesCandidate() throws {
        XCTAssertEqual(try aligned(speakers: [speaker("speaker_1", 2, 4)]).segments[0].speakerCandidates, ["speaker_1"])
    }
    func testOverlappingSpeakersProduceMultipleCandidates() throws {
        XCTAssertEqual(try aligned(speakers: [speaker("speaker_2", 1, 2), speaker("speaker_1", 1.5, 2.5)]).segments[0].speakerCandidates, ["speaker_1", "speaker_2"])
    }
    func testNoOverlapProducesUnmatched() throws {
        let entry = try aligned(speakers: [speaker("speaker_1", 3, 4)]).segments[0]
        XCTAssertTrue(entry.speakerCandidates.isEmpty)
    }
    func testRejectsSourceHashMismatch() {
        XCTAssertThrowsError(try aligned(transcriptHash: "a", speakerHash: "b", speakers: [try speaker("s", 1, 2)]))
    }
    func testRejectsRecordingStartMismatch() {
        XCTAssertThrowsError(try aligned(transcriptStart: "a", speakerStart: "b", speakers: [try speaker("s", 1, 2)]))
    }
}
