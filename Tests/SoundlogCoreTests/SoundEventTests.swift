import XCTest
@testable import SoundlogCore

final class SoundEventTests: XCTestCase {
    private let start = try! RecordingStart(filename: "20240229235959.wav")
    private let parameters = SoundEventParameters(confidenceThreshold: 0.5, minimumEventDurationSeconds: 0.1, mergeGapSeconds: 0.5)

    func testSoundEventParametersParseFromCLIValues() throws {
        let parsed = try CLIOptions.parse([
            "sound-events", "--input", "/tmp/in", "--output-dir", "/tmp/out",
            "--param", "confidenceThreshold=0.72",
            "--param", "minimumEventDurationSeconds=1.25",
            "--param", "mergeGapSeconds=0.4"
        ])
        let parameters = try SoundEventParameterParser.parse(parsed.parameters)
        XCTAssertEqual(parameters, SoundEventParameters(confidenceThreshold: 0.72, minimumEventDurationSeconds: 1.25, mergeGapSeconds: 0.4))
    }

    func testSoundEventParametersRejectInvalidValues() {
        for values: [String: String] in [
            ["confidenceThreshold": "NaN"],
            ["confidenceThreshold": "1.01"],
            ["minimumEventDurationSeconds": "-0.1"],
            ["mergeGapSeconds": "not-a-number"],
            ["unrecognized": "1"]
        ] {
            XCTAssertThrowsError(try SoundEventParameterParser.parse(values), "Expected rejection for \\(values)")
        }
    }

    func testNoSpeechAmbientSoundCreatesEvent() throws {
        let events = try build([window(0, 1, "rain", 0.9)])
        XCTAssertEqual(events.map(\.category), ["rain"])
    }

    func testSustainedSoundCreatesOneEvent() throws {
        let events = try build([window(0, 1, "fan", 0.8), window(1, 2, "fan", 0.9)])
        XCTAssertEqual(events.count, 1); XCTAssertEqual(events[0].startOffsetSeconds, 0); XCTAssertEqual(events[0].endOffsetSeconds, 2)
    }

    func testIntermittentSoundMergesWhenGapIsSmallerThanLimit() throws {
        let events = try build([window(0, 1, "rain", 0.9), window(1.4, 2, "rain", 0.8)])
        XCTAssertEqual(events.count, 1); XCTAssertEqual(events[0].sourceWindowIndices, [0, 1])
    }

    func testIntermittentSoundSplitsWhenGapIsLargerThanLimit() throws {
        let events = try build([window(0, 1, "rain", 0.9), window(1.6, 2, "rain", 0.8)])
        XCTAssertEqual(events.count, 2)
    }

    func testMultipleOverlappingSoundsCreateSeparateEvents() throws {
        let events = try build([SoundClassificationWindow(start: 0, end: 1, candidates: [.init(category: "rain", confidence: 0.9), .init(category: "speech", confidence: 0.8)])])
        XCTAssertEqual(Set(events.map(\.category)), ["rain", "speech"])
    }

    func testUnknownCandidateCreatesUnknownEvent() throws {
        let events = try build([window(0, 0.8, "bird", 0.1)])
        XCTAssertEqual(events.map(\.category), ["unknown"])
    }

    func testLowConfidenceCandidateRemainsInUnknownWindow() async throws {
        let doc = try await pipeline([window(0, 0.8, "bird", 0.2)])
        XCTAssertEqual(doc.windows[0].candidates.map(\.category), ["bird"])
        XCTAssertEqual(doc.windows[0].classificationStatus, "unknown")
    }

    func testMinimumDurationFiltersShortEvent() throws {
        let events = try build([window(0, 0.05, "click", 0.9)], minimumDuration: 0.2)
        XCTAssertTrue(events.isEmpty)
    }

    func testEventIndicesResolveBackToWindowCandidates() async throws {
        let doc = try await pipeline([window(0, 0.4, "rain", 0.8)])
        let event = try XCTUnwrap(doc.events.first)
        XCTAssertEqual(doc.windows[event.sourceWindowIndices[0]].candidates[0].category, event.category)
    }

    func testNonzeroWindowOffsetsMapAcrossMidnightLikeTimeline() throws {
        let events = try build([window(3.5, 5.25, "rain", 0.9)])
        let event = try XCTUnwrap(events.first)
        XCTAssertEqual(event.absoluteStartLocal, "2024-03-01T00:00:02.500")
        XCTAssertEqual(event.absoluteEndLocal, "2024-03-01T00:00:04.250")
        XCTAssertEqual(event.absoluteStartLocal, try start.timestamp(atOffsetSeconds: 3.5))
        XCTAssertEqual(event.absoluteEndLocal, try start.timestamp(atOffsetSeconds: 5.25))
    }

    func testPipelineWritesDocumentAndParameters() async throws {
        let doc = try await pipeline([window(0, 0.4, "rain", 0.8)])
        XCTAssertEqual(doc.parameters, parameters)
        XCTAssertTrue(doc.windowBoundaryCaveat.contains("不等于"))
    }

    private func window(_ a: Double, _ b: Double, _ category: String, _ confidence: Double) -> SoundClassificationWindow {
        SoundClassificationWindow(start: a, end: b, candidates: [.init(category: category, confidence: confidence)])
    }
    private func build(_ windows: [SoundClassificationWindow], minimumDuration: Double? = nil) throws -> [SoundEvent] {
        let p = SoundEventParameters(confidenceThreshold: parameters.confidenceThreshold, minimumEventDurationSeconds: minimumDuration ?? parameters.minimumEventDurationSeconds, mergeGapSeconds: parameters.mergeGapSeconds)
        return try SoundEventBuilder.events(windows: windows, parameters: p, recordingStart: start)
    }
    private func pipeline(_ windows: [SoundClassificationWindow]) async throws -> SoundEventsDocument {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent("20240229235959.wav"); try Data("fixture".utf8).write(to: file)
        return try await SoundEventPipeline(engine: SyntheticSoundEngine(windows: windows)).run(file: file, runDirectory: dir.appendingPathComponent("out"), parameters: parameters)
    }
}

private struct SyntheticSoundEngine: SoundEventEngine {
    let windows: [SoundClassificationWindow]
    var identifier: String { "synthetic" }
    func classify(file: URL) async throws -> SoundEventEngineResult { SoundEventEngineResult(windows: windows) }
}
