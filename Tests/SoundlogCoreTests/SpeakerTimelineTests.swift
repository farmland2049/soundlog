import XCTest
@testable import SoundlogCore

final class SpeakerTimelineTests: XCTestCase {
    func testPipelineWritesAnonymousTimelineWithAbsoluteTimesAndOverlaps() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent("20240229235959.wav")
        try Data("fixture".utf8).write(to: file)
        let engine = SyntheticSpeakerEngine(segments: [
            SpeakerSegment(speakerID: "speaker_1", startOffsetSeconds: 1, endOffsetSeconds: 3),
            SpeakerSegment(speakerID: nil, startOffsetSeconds: 2, endOffsetSeconds: 2.5)
        ])

        let document = try await SpeakerTimelinePipeline(engine: engine).run(file: file, runDirectory: dir)

        XCTAssertEqual(document.accuracyAssessment, "not_evaluated")
        XCTAssertEqual(document.segments.count, 2)
        XCTAssertEqual(document.segments[0].absoluteStartLocal, "2024-03-01T00:00:00.000")
        XCTAssertEqual(document.segments[0].absoluteEndLocal, "2024-03-01T00:00:02.000")
        XCTAssertNil(document.segments[1].speakerID)
        let saved = try Data(contentsOf: dir.appendingPathComponent("speaker-timeline.json"))
        XCTAssertTrue(String(decoding: saved, as: UTF8.self).contains("speaker_1"))
    }

    func testPipelineRejectsOutOfOrderSegments() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent("20240229235959.wav")
        try Data("fixture".utf8).write(to: file)
        let engine = SyntheticSpeakerEngine(segments: [
            SpeakerSegment(speakerID: "speaker_1", startOffsetSeconds: 3, endOffsetSeconds: 4),
            SpeakerSegment(speakerID: "speaker_2", startOffsetSeconds: 1, endOffsetSeconds: 2)
        ])

        do {
            _ = try await SpeakerTimelinePipeline(engine: engine).run(file: file, runDirectory: dir)
            XCTFail("Expected out-of-order segments to be rejected")
        } catch let error as TimelineError {
            XCTAssertEqual(error, .outOfOrderRanges)
        }
    }
}

private struct SyntheticSpeakerEngine: SpeakerDiarizationEngine {
    let segments: [SpeakerSegment]
    var identifier: String { "synthetic" }
    func diarize(file: URL) async throws -> SpeakerEngineResult { SpeakerEngineResult(segments: segments) }
}
