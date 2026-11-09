import XCTest
@testable import SoundlogCore

final class IntegratedProcessingTests: XCTestCase {
    func testRejectsInvalidTimesAndCoverage() throws {
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: 1, endOffsetSeconds: 1))
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: -1, endOffsetSeconds: 1))
        XCTAssertThrowsError(try IntegratedArtifactValidator.validate(coverage: []))
        XCTAssertThrowsError(try IntegratedArtifactValidator.validate(coverage: [try AudioTimeRange(startOffsetSeconds: 2, endOffsetSeconds: 3), try AudioTimeRange(startOffsetSeconds: 1, endOffsetSeconds: 2)]))
    }
    func testModelMissingFailureStateIsSerializable() throws {
        var status = IntegratedProcessingStatus(sourcePath: "synthetic", sourceSHA256: "hash")
        status.record("speakerDiarization", state: "failed", error: "model missing")
        try IntegratedArtifactValidator.validate(status: status)
        let data = try JSONEncoder().encode(status)
        let decoded = try JSONDecoder().decode(IntegratedProcessingStatus.self, from: data)
        XCTAssertEqual(decoded.modules["speakerDiarization"]?.error, "model missing")
    }
    func testResumeReusesMatchingHashParametersAndEngine() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "sourceSHA256": "hash", "engine": "engine-v1", "parameters": ["threshold": 0.3]]).write(to: file)
        let fingerprint = ResumeFingerprint(sourceSHA256: "hash", engine: "engine-v1", parameters: ["threshold": "0.3"])
        let completed = IntegratedModuleStatus(state: "completed", fingerprint: fingerprint)
        XCTAssertEqual(IntegratedModuleResumePlanner.plan(expected: fingerprint, status: completed, artifactURL: file), .reuse)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: .init(sourceSHA256: "other", engine: "engine-v1", parameters: ["threshold": "0.3"]), status: completed, artifactURL: file), .reuse)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: .init(sourceSHA256: "hash", engine: "engine-v1", parameters: ["threshold": "0.4"]), status: completed, artifactURL: file), .reuse)
    }

    func testCandidateTranscriptShowsUnmatchedAndAllAnonymousCandidates() {
        let entries = [
            SpeakerAlignedTranscriptEntry(startOffsetSeconds: 0, endOffsetSeconds: 1, absoluteStartLocal: "2026-01-01T00:00:00.000", absoluteEndLocal: "2026-01-01T00:00:01.000", speakerCandidates: [], hasUnattributedOverlap: false, text: "无候选"),
            SpeakerAlignedTranscriptEntry(startOffsetSeconds: 1, endOffsetSeconds: 2, absoluteStartLocal: "2026-01-01T00:00:01.000", absoluteEndLocal: "2026-01-01T00:00:02.000", speakerCandidates: ["speaker-2", "speaker-1"], hasUnattributedOverlap: false, text: "多候选")
        ]
        let doc = SpeakerAlignedTranscriptDocument(schemaVersion: 1, sourcePath: "synthetic", sourceSHA256: "hash", recordingStartLocal: "2026-01-01T00:00:00.000", transcriptionEngine: "test", diarizationEngine: "test", alignmentMethod: "overlap", accuracyAssessment: "not_evaluated", segments: entries)
        let md = UnifiedOutput.renderTranscript(doc, format: "md")
        XCTAssertTrue(md.contains("说话人候选：未匹配"))
        XCTAssertTrue(md.contains("speaker-1、speaker-2"))
        XCTAssertFalse(md.contains("Alice"))
    }

    func testCoverageReportsLeadingInteriorAndTrailingGaps() throws {
        let report = try UnifiedOutput.coverageReport(ranges: [AudioTimeRange(startOffsetSeconds: 2, endOffsetSeconds: 4), AudioTimeRange(startOffsetSeconds: 5, endOffsetSeconds: 7)], duration: 9)
        XCTAssertEqual(report.gaps.map(\.start), [0, 4, 7])
        XCTAssertEqual(report.coveredSeconds, 4)
    }

    func testSamplesTakeFirstMiddleLast() {
        let result = UnifiedOutput.samples((0..<9).map(String.init), count: 2)
        XCTAssertEqual(result.first, ["0", "1"])
        XCTAssertEqual(result.middle, ["3", "4"])
        XCTAssertEqual(result.last, ["7", "8"])
    }

    func testManifestSurvivesModuleFailureAndHashesArtifacts() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let artifact = root.appendingPathComponent("sample.json")
        try Data("synthetic".utf8).write(to: artifact)
        let manifest = try UnifiedOutput.buildManifest(inputPath: "synthetic.wav", sourceSHA256: "source", duration: nil, coverageRanges: [], modules: ["speaker": IntegratedModuleStatus(state: "failed", error: "model missing")], samples: [:], artifactURLs: ["sample": artifact], baseDirectory: root, generatedAt: "fixed")
        XCTAssertEqual(manifest.modules["speaker"]?.error, "model missing")
        XCTAssertEqual(manifest.artifacts["sample"]?.sha256, SHA256.digest(Data("synthetic".utf8)))
    }

    func testFailedAtomicWriteLeavesNoTemporaryArtifact() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let blocker = root.appendingPathComponent("not-a-directory")
        try Data().write(to: blocker)
        XCTAssertThrowsError(try AtomicFile.write(Data("nope".utf8), to: blocker.appendingPathComponent("result.txt")))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), ["not-a-directory"])
    }

    func testArtifactWriteFailureCanBeRecordedWithReason() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let blocker = root.appendingPathComponent("blocked")
        try Data().write(to: blocker)
        var status = IntegratedProcessingStatus(sourcePath: "synthetic", sourceSHA256: "hash")
        let target = blocker.appendingPathComponent("transcript.md")
        do {
            try AtomicFile.write(Data("synthetic".utf8), to: target)
            XCTFail("Expected the destination write to fail")
        } catch {
            status.record("unifiedTranscript", state: "failed", error: String(describing: error))
        }
        let statusURL = root.appendingPathComponent("status.json")
        try AtomicFile.write(try JSONEncoder().encode(status), to: statusURL)
        let saved = try JSONDecoder().decode(IntegratedProcessingStatus.self, from: Data(contentsOf: statusURL))
        XCTAssertEqual(saved.modules["unifiedTranscript"]?.state, "failed")
        XCTAssertFalse(saved.modules["unifiedTranscript"]?.error?.isEmpty ?? true)
        XCTAssertFalse(FileManager.default.fileExists(atPath: target.path))
    }

    func testWAVDurationReadsSyntheticHeader() {
        var data = Data("RIFF".utf8); data.append(contentsOf: [0xa4,0x3e,0,0]); data.append(Data("WAVEfmt ".utf8));
        data.append(contentsOf: [16,0,0,0, 1,0, 1,0, 0x40,0x1f,0,0, 0x80,0x3e,0,0, 2,0,16,0]); data.append(Data("data".utf8)); data.append(contentsOf: [0x80,0x3e,0,0]); data.append(Data(repeating: 0, count: 16000))
        XCTAssertEqual(UnifiedOutput.wavDuration(data: data), 1)
    }
}
