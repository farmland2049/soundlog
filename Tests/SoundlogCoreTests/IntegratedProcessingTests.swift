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
}
