import XCTest
@testable import SoundlogCore

final class TranscriptionTests: XCTestCase {
    func testCLIParsing() throws {
        let parsed = try CLIOptions.parse(["manifest", "--input", "/tmp/in", "--output-dir", "/tmp/out", "--run-dir", "/tmp/run", "--param", "locale=en"])
        XCTAssertEqual(parsed.command, .manifest); XCTAssertEqual(parsed.parameters["locale"], "en")
        XCTAssertEqual(parsed.runDirectory?.path, "/tmp/run")
        XCTAssertEqual(try CLIOptions.parse(["speaker-diarize", "--input", "x", "--output-dir", "y"]).command, .speakerDiarize)
        XCTAssertEqual(try CLIOptions.parse(["process", "--input", "x", "--output-dir", "y"]).command, .process)
        XCTAssertThrowsError(try CLIOptions.parse(["transcribe", "--input", "x"]))
        XCTAssertThrowsError(try CLIOptions.parse(["bogus", "--input", "x", "--output-dir", "y"]))
        XCTAssertThrowsError(try CLIOptions.parse(["manifest", "--input", "x", "--output-dir", "y", "--param", "bad"]))
    }

    func testInputEnumerationForFileAndSortedFolder() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: root) }
        for name in ["z.MP3", "a.wav", "ignore.txt"] { try Data([1,2]).write(to: root.appendingPathComponent(name)) }
        XCTAssertEqual(try InputEnumerator.files(at: root).map(\.lastPathComponent), ["a.wav", "z.MP3"])
        XCTAssertEqual(try InputEnumerator.files(at: root.appendingPathComponent("z.MP3")).count, 1)
    }

    func testSHA256KnownVectors() {
        XCTAssertEqual(SHA256.digest(Data()), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        XCTAssertEqual(SHA256.digest(Data("abc".utf8)), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }

    func testResumeRequiresAllFingerprintFieldsToMatch() {
        let original = ResumeFingerprint(sourceSHA256: "a", engine: "e", parameters: ["x":"1"])
        XCTAssertTrue(original.mayReuse(original))
        XCTAssertFalse(original.mayReuse(ResumeFingerprint(sourceSHA256: "b", engine: "e", parameters: ["x":"1"])))
        XCTAssertFalse(original.mayReuse(ResumeFingerprint(sourceSHA256: "a", engine: "other", parameters: ["x":"1"])))
        XCTAssertFalse(original.mayReuse(ResumeFingerprint(sourceSHA256: "a", engine: "e", parameters: ["x":"2"])))
    }

    func testCoverageIsIndependentFromWordsAndEmptyHasExplicitState() async throws {
        let dir = try fixtureDirectory(); defer { try? FileManager.default.removeItem(at: dir) }
        let source = try fakeSource(in: dir)
        let blankEngine = FakeEngine(identifier: "fake", result: EngineResult(segments: [TranscriptSegment(start: 1, end: 2, text: " \n")], coveredRanges: [try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 10)]))
        _ = try await TranscriptionPipeline(engine: blankEngine).run(file: source, runDirectory: dir.appendingPathComponent("blank"))
        let raw = try JSONDecoder().decode(RawTranscription.self, from: Data(contentsOf: dir.appendingPathComponent("blank/raw.json")))
        XCTAssertEqual(raw.status, "completed_no_text"); XCTAssertEqual(raw.coverage.count, 1); XCTAssertTrue(raw.textRanges.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("blank/transcript.md").path))
    }

    func testResumePlannerReasonsAndMissingRaw() throws {
        let dir = try fixtureDirectory(); defer { try? FileManager.default.removeItem(at: dir) }
        let fp = ResumeFingerprint(sourceSHA256: "h", engine: "e", parameters: ["locale":"zh-CN"])
        let statusURL = dir.appendingPathComponent("status.json"), rawURL = dir.appendingPathComponent("raw.json")
        XCTAssertEqual(ResumePlanner.plan(expected: fp, statusURL: statusURL, rawURL: rawURL), .rerun("无记录"))
        let enc = JSONEncoder()
        try enc.encode(TranscriptionStatus(state: .completedWithText, fingerprint: fp)).write(to: statusURL)
        XCTAssertEqual(ResumePlanner.plan(expected: fp, statusURL: statusURL, rawURL: rawURL), .rerun("产物缺失"))
        try Data().write(to: rawURL)
        XCTAssertEqual(ResumePlanner.plan(expected: fp, statusURL: statusURL, rawURL: rawURL), .reuse)
        XCTAssertEqual(ResumePlanner.plan(expected: ResumeFingerprint(sourceSHA256: "other", engine: "e", parameters: fp.parameters), statusURL: statusURL, rawURL: rawURL), .rerun("哈希变"))
        XCTAssertEqual(ResumePlanner.plan(expected: ResumeFingerprint(sourceSHA256: "h", engine: "other", parameters: fp.parameters), statusURL: statusURL, rawURL: rawURL), .rerun("引擎变"))
        XCTAssertEqual(ResumePlanner.plan(expected: ResumeFingerprint(sourceSHA256: "h", engine: "e", parameters: [:]), statusURL: statusURL, rawURL: rawURL), .rerun("参数变"))
        try enc.encode(TranscriptionStatus(state: .failed, error: "boom", fingerprint: fp)).write(to: statusURL)
        XCTAssertEqual(ResumePlanner.plan(expected: fp, statusURL: statusURL, rawURL: rawURL), .rerun("上次失败"))
    }

    func testTranscriptionRunFailureDoesNotReuseAndSuccessReuses() async throws {
        let dir = try fixtureDirectory(); defer { try? FileManager.default.removeItem(at: dir) }
        let source = try fakeSource(in: dir)
        let failed = TranscriptionRun(engine: FailingEngine())
        let first = await failed.process(files: [source], runDirectory: dir.appendingPathComponent("run"))
        let output = first[0].outputDirectory
        let status = try JSONDecoder().decode(TranscriptionStatus.self, from: Data(contentsOf: output.appendingPathComponent("status.json")))
        XCTAssertEqual(status.state, .failed); XCTAssertNotNil(status.error)
        XCTAssertEqual(ResumePlanner.plan(expected: status.fingerprint, statusURL: output.appendingPathComponent("status.json"), rawURL: output.appendingPathComponent("raw.json")), .rerun("上次失败"))
        let good = FakeEngine(identifier: "fake", result: EngineResult(segments: [TranscriptSegment(start: 1, end: 2, text: "yes")], coveredRanges: [try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 5)]))
        let run = TranscriptionRun(engine: good)
        _ = await run.process(files: [source], runDirectory: dir.appendingPathComponent("run"))
        let again = await run.process(files: [source], runDirectory: dir.appendingPathComponent("run"))
        XCTAssertEqual(again[0].decision, .reuse)
    }

    func testTranscriptionRunExitStatusReflectsOneRealEngineFailure() async throws {
        let dir = try fixtureDirectory(); defer { try? FileManager.default.removeItem(at: dir) }
        let good = try fakeSource(in: dir, filename: "20261109000000.wav")
        let bad = try fakeSource(in: dir, filename: "20261109000001.wav")
        let result = EngineResult(segments: [TranscriptSegment(start: 0, end: 1, text: "ok")], coveredRanges: [try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 2)])
        let run = TranscriptionRun(engine: SelectiveFailureEngine(result: result))
        let outcomes = await run.process(files: [good, bad], runDirectory: dir.appendingPathComponent("partial"))
        XCTAssertEqual(outcomes.count, 2)
        XCTAssertFalse(outcomes[0].failed)
        XCTAssertTrue(outcomes[1].failed)
        XCTAssertNotEqual(TranscriptionExitStatus.exitCode(for: outcomes), 0)

        let success = await TranscriptionRun(engine: FakeEngine(identifier: "good", result: result)).process(files: [good], runDirectory: dir.appendingPathComponent("success"))
        XCTAssertEqual(TranscriptionExitStatus.exitCode(for: success), 0)
    }

    func testInjectedEngineWritesRawSeparatelyFromRenderedAbsoluteTranscript() async throws {
        let dir = try fixtureDirectory(); defer { try? FileManager.default.removeItem(at: dir) }
        let source = try fakeSource(in: dir, filename: "20240229235959.wav")
        let engine = FakeEngine(identifier: "synthetic", result: EngineResult(segments: [TranscriptSegment(start: 2, end: 3, text: "hello")], coveredRanges: [try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 8)]))
        let out = dir.appendingPathComponent("run")
        let raw = try await TranscriptionPipeline(engine: engine).run(file: source, runDirectory: out)
        XCTAssertEqual(raw.status, "completed_with_text")
        XCTAssertEqual(raw.coverage, [AudioTimeRangeCodable(try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 8))])
        XCTAssertEqual(raw.textRanges, [AudioTimeRangeCodable(try AudioTimeRange(startOffsetSeconds: 2, endOffsetSeconds: 3))])
        let json = try Data(contentsOf: out.appendingPathComponent("raw.json"))
        let markdown = try String(contentsOf: out.appendingPathComponent("transcript.md"), encoding: .utf8)
        XCTAssertTrue(String(decoding: json, as: UTF8.self).contains("startOffsetSeconds"))
        XCTAssertTrue(markdown.contains("2024-03-01T00:00:01.000")); XCTAssertTrue(markdown.contains("hello"))
    }

    func testWordsMustFallInsideProcessedCoverage() async throws {
        let dir = try fixtureDirectory(); defer { try? FileManager.default.removeItem(at: dir) }
        let source = try fakeSource(in: dir)
        let engine = FakeEngine(identifier: "fake", result: EngineResult(segments: [TranscriptSegment(start: 4, end: 5, text: "out")], coveredRanges: [try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 3)]))
        do { _ = try await TranscriptionPipeline(engine: engine).run(file: source, runDirectory: dir.appendingPathComponent("bad")); XCTFail("out of coverage") } catch TranscriptionError.invalidCoverage {}
    }

    private func fixtureDirectory() throws -> URL { let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString); try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true); return url }
    private func fakeSource(in dir: URL, filename: String = "20261109000000.wav") throws -> URL { let url = dir.appendingPathComponent(filename); try Data("synthetic audio placeholder".utf8).write(to: url); return url }
}

private struct FakeEngine: TranscriptionEngine {
    let identifier: String; let result: EngineResult
    func transcribe(file: URL) async throws -> EngineResult { result }
}
private struct FailingEngine: TranscriptionEngine {
    var identifier: String { "fake" }
    func transcribe(file: URL) async throws -> EngineResult { throw TranscriptionError.io("synthetic failure") }
}
private struct SelectiveFailureEngine: TranscriptionEngine {
    let result: EngineResult
    var identifier: String { "selective" }
    func transcribe(file: URL) async throws -> EngineResult {
        if file.lastPathComponent == "20261109000001.wav" { throw TranscriptionError.io("synthetic failure") }
        return result
    }
}
