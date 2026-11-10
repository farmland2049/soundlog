import XCTest
@testable import SoundlogCore

private final class ExecutorCallCounter: @unchecked Sendable { var value = 0 }
private final class CountingArtifactHasher: ArtifactHashing, @unchecked Sendable {
    let calls = ExecutorCallCounter()
    func hash(file url: URL) throws -> String { calls.value += 1; return try SHA256.file(url) }
}
private struct ENOSPCWriter: AtomicFileWriting {
    func write(_ data: Data, to destination: URL) throws { throw NSError(domain: NSPOSIXErrorDomain, code: 28) }
}
private struct ENOSPCStreamingWriter: AtomicFileStreamingWriting {
    func writeStreaming(to destination: URL, body: (FileHandle) throws -> Void) throws { throw NSError(domain: NSCocoaErrorDomain, code: 640) }
}

final class IntegratedProcessingTests: XCTestCase {
    func testSoundEventSidecarMustBeCompleteAndMatchSummaryCount() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: root) }
        let summary = root.appendingPathComponent("sound-events.json"), sidecar = root.appendingPathComponent("sound-event-windows.ndjson")
        try Data("{\"schemaVersion\":1,\"sourceSHA256\":\"hash\",\"engine\":\"engine\",\"parameters\":{},\"windowCount\":2}".utf8).write(to: summary)
        let rows = "{\"startOffsetSeconds\":0,\"endOffsetSeconds\":1,\"candidates\":[],\"classificationStatus\":\"unknown\"}\n{\"startOffsetSeconds\":1,\"endOffsetSeconds\":2,\"candidates\":[],\"classificationStatus\":\"unknown\"}\n"
        let fp = ResumeFingerprint(sourceSHA256: "hash", engine: "engine", parameters: [:])
        let completed = IntegratedModuleStatus(state: "completed", fingerprint: fp)
        func decision(_ bytes: String?) -> ResumeDecision {
            if let bytes { try? Data(bytes.utf8).write(to: sidecar) } else { try? FileManager.default.removeItem(at: sidecar) }
            return IntegratedModuleResumePlanner.plan(expected: fp, status: completed, artifactURL: summary, sidecarURL: sidecar)
        }
        XCTAssertEqual(decision(rows), .reuse)
        XCTAssertNotEqual(decision(""), .reuse)
        XCTAssertNotEqual(decision(String(rows.dropLast(2))), .reuse)
        let firstLine = String(rows.split(separator: "\n")[0])
        XCTAssertNotEqual(decision(rows.replacingOccurrences(of: firstLine, with: "{bad}")), .reuse)
        XCTAssertNotEqual(decision(nil), .reuse)
    }

    func testSoundEventSidecarMaxLineBytesRejectsOverlongRowAndTriggersRerun() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(at: root) }
        let summary = root.appendingPathComponent("sound-events.json"), sidecar = root.appendingPathComponent("sound-event-windows.ndjson")
        try Data("{\"schemaVersion\":1,\"sourceSHA256\":\"hash\",\"engine\":\"engine\",\"parameters\":{},\"windowCount\":1}".utf8).write(to: summary)
        let row = "{\"startOffsetSeconds\":0,\"endOffsetSeconds\":1,\"candidates\":[],\"classificationStatus\":\"unknown\"}\n"
        try Data(row.utf8).write(to: sidecar)

        XCTAssertNoThrow(try SoundEventSidecarValidator.validate(summaryURL: summary, sidecarURL: sidecar))

        XCTAssertThrowsError(try SoundEventSidecarValidator.validate(summaryURL: summary, sidecarURL: sidecar, maxLineBytes: 30)) { error in
            XCTAssertTrue(String(describing: error).contains("超出最大限制"))
        }

        let originalLimit = SoundEventSidecarValidator.maxLineBytes
        defer { SoundEventSidecarValidator.maxLineBytes = originalLimit }
        SoundEventSidecarValidator.maxLineBytes = 30

        let fp = ResumeFingerprint(sourceSHA256: "hash", engine: "engine", parameters: [:])
        let completed = IntegratedModuleStatus(state: "completed", fingerprint: fp)
        let decision = IntegratedModuleResumePlanner.plan(expected: fp, status: completed, artifactURL: summary, sidecarURL: sidecar)
        XCTAssertEqual(decision, .rerun("声音事件候选 sidecar 缺失或无效"))
    }

    func testSkipCapturesResidentMemoryAndDiskFullVariantsAreRecognized() async throws {
        let statusURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: statusURL) }
        var status = IntegratedProcessingStatus(sourcePath: "synthetic", sourceSHA256: "hash")
        IntegratedModuleExecutor.skip(module: "unsupported", state: "unsupported", reason: "platform", status: &status, statusURL: statusURL)
        let skipped = try XCTUnwrap(status.modules["unsupported"])
        XCTAssertGreaterThan(skipped.residentBytesBefore ?? 0, 0); XCTAssertGreaterThan(skipped.residentBytesAfter ?? 0, 0); XCTAssertGreaterThan(skipped.processPeakResidentBytes ?? 0, 0)
        for error in [NSError(domain: NSCocoaErrorDomain, code: 640), NSError(domain: "wrapper", code: 1, userInfo: [NSUnderlyingErrorKey: NSError(domain: NSPOSIXErrorDomain, code: 28)])] {
            let module = UUID().uuidString
            let ok = await IntegratedModuleExecutor.execute(module: module, fingerprint: ResumeFingerprint(sourceSHA256: "hash", engine: "x", parameters: [:]), status: &status, statusURL: statusURL) { throw error }
            XCTAssertFalse(ok); XCTAssertTrue(status.modules[module]?.error?.contains("ENOSPC") == true)
        }
        XCTAssertThrowsError(try AtomicFile.writeStreaming(to: statusURL, using: ENOSPCStreamingWriter()) { _ in })
    }

    func testExecutorRecomputesReusesAndInvalidatesThroughRealOperations() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let artifact = root.appendingPathComponent("raw.json")
        let statusURL = root.appendingPathComponent("processing-status.json")
        var status = IntegratedProcessingStatus(sourcePath: "synthetic.wav", sourceSHA256: "hash")
        let calls = ExecutorCallCounter()
        func operation(_ fingerprint: ResumeFingerprint) -> @Sendable () async throws -> Void {
            { calls.value += 1; let value: [String: Any] = ["schemaVersion": 1, "sourceSHA256": fingerprint.sourceSHA256, "engine": fingerprint.engine, "parameters": fingerprint.parameters.mapValues { value in Double(value) ?? 0.3 }]; try JSONSerialization.data(withJSONObject: value).write(to: artifact) }
        }
        let first = ResumeFingerprint(sourceSHA256: "hash", engine: "fake-engine", parameters: ["threshold": "0.3"])
        let result = await IntegratedModuleExecutor.execute(module: "transcription", fingerprint: first, artifactURL: artifact, status: &status, statusURL: statusURL, operation: operation(first))
        XCTAssertTrue(result)
        XCTAssertEqual(calls.value, 1)
        XCTAssertEqual(status.modules["transcription"]?.execution, "recomputed")
        XCTAssertNotNil(status.modules["transcription"]?.wallClockSeconds)
        XCTAssertGreaterThan(status.modules["transcription"]?.residentBytesBefore ?? 0, 0)
        XCTAssertGreaterThan(status.modules["transcription"]?.residentBytesAfter ?? 0, 0)
        XCTAssertGreaterThan(status.modules["transcription"]?.processPeakResidentBytes ?? 0, 0)

        let reused = await IntegratedModuleExecutor.execute(module: "transcription", fingerprint: first, artifactURL: artifact, status: &status, statusURL: statusURL, operation: operation(first))
        XCTAssertTrue(reused)
        XCTAssertEqual(calls.value, 1)
        XCTAssertEqual(status.modules["transcription"]?.execution, "reuse")
        XCTAssertNotNil(status.modules["transcription"]?.wallClockSeconds)

        try Data("broken".utf8).write(to: artifact)
        let repaired = await IntegratedModuleExecutor.execute(module: "transcription", fingerprint: first, artifactURL: artifact, status: &status, statusURL: statusURL, operation: operation(first))
        XCTAssertTrue(repaired)
        XCTAssertEqual(calls.value, 2)
        XCTAssertEqual(status.modules["transcription"]?.execution, "recomputed")
        XCTAssertNotNil(status.modules["transcription"]?.wallClockSeconds)

        let changed = ResumeFingerprint(sourceSHA256: "hash", engine: "fake-engine", parameters: ["threshold": "0.4"])
        let changedResult = await IntegratedModuleExecutor.execute(module: "transcription", fingerprint: changed, artifactURL: artifact, status: &status, statusURL: statusURL, operation: operation(changed))
        XCTAssertTrue(changedResult)
        XCTAssertEqual(calls.value, 3)
        XCTAssertEqual(status.modules["transcription"]?.execution, "recomputed")
        XCTAssertNotNil(status.modules["transcription"]?.wallClockSeconds)
    }
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

    func testInjectedModelFailureIsPersistedAndLaterModuleAndManifestRun() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let statusURL = root.appendingPathComponent("processing-status.json")
        let fingerprint = ResumeFingerprint(sourceSHA256: "synthetic-hash", engine: "fake-speaker-engine", parameters: [:])
        var status = IntegratedProcessingStatus(sourcePath: "synthetic.mp3", sourceSHA256: "synthetic-hash")
        let failed = await IntegratedModuleExecutor.execute(module: "speakerDiarization", fingerprint: fingerprint, status: &status, statusURL: statusURL) {
            throw TranscriptionError.io("model missing")
        }
        XCTAssertFalse(failed)
        let savedFailure = try JSONDecoder().decode(IntegratedProcessingStatus.self, from: Data(contentsOf: statusURL))
        XCTAssertEqual(savedFailure.modules["speakerDiarization"]?.state, "failed")
        XCTAssertTrue(savedFailure.modules["speakerDiarization"]?.error?.contains("model missing") == true)

        let otherFingerprint = ResumeFingerprint(sourceSHA256: "synthetic-hash", engine: "synthetic-other", parameters: [:])
        let artifact = root.appendingPathComponent("other-module.json")
        let succeeded = await IntegratedModuleExecutor.execute(module: "otherModule", fingerprint: otherFingerprint, status: &status, statusURL: statusURL) {
            try AtomicFile.write(Data("complete".utf8), to: artifact)
        }
        XCTAssertTrue(succeeded)
        let blocker = root.appendingPathComponent("not-a-directory")
        try Data("blocker".utf8).write(to: blocker)
        let failedWrite = await IntegratedModuleExecutor.execute(module: "artifactWriter", fingerprint: otherFingerprint, status: &status, statusURL: statusURL) {
            try AtomicFile.write(Data("partial".utf8), to: blocker.appendingPathComponent("artifact.json"))
        }
        XCTAssertFalse(failedWrite)
        XCTAssertEqual(status.modules["artifactWriter"]?.state, "failed")
        XCTAssertFalse(FileManager.default.fileExists(atPath: blocker.appendingPathComponent("artifact.json").path))
        let manifestURL = root.appendingPathComponent("run-manifest.json")
        let manifest = try UnifiedOutput.writeManifest(inputPath: "synthetic.mp3", sourceSHA256: "synthetic-hash", duration: nil, coverageRanges: [], modules: status.modules, samples: [:], artifactURLs: ["other": artifact], baseDirectory: root, to: manifestURL, durationMethod: "frame-scan", durationError: nil, performance: RunPerformance(wallClockSeconds: 0.1, peakMemoryBytes: 1234, peakMemorySource: "getrusage", ruMaxRSSUnit: "KB"))
        XCTAssertEqual(manifest.modules["speakerDiarization"]?.state, "failed")
        XCTAssertEqual(manifest.modules["otherModule"]?.state, "completed")
        XCTAssertEqual(manifest.modules["artifactWriter"]?.state, "failed")
        XCTAssertTrue(FileManager.default.fileExists(atPath: manifestURL.path))
    }
    func testResumeReusesMatchingHashParametersAndEngine() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "sourceSHA256": "hash", "engine": "engine-v1", "parameters": ["threshold": 0.3]]).write(to: file)
        let fingerprint = ResumeFingerprint(sourceSHA256: "hash", engine: "engine-v1", parameters: ["threshold": "0.3"])
        let completed = IntegratedModuleStatus(state: "completed", fingerprint: fingerprint)
        XCTAssertEqual(IntegratedModuleResumePlanner.plan(expected: fingerprint, status: completed, artifactURL: file), .reuse)
        try Data("damaged".utf8).write(to: file)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: fingerprint, status: completed, artifactURL: file), .reuse)
        try FileManager.default.removeItem(at: file)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: fingerprint, status: completed, artifactURL: file), .reuse)
        try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "sourceSHA256": "hash", "engine": "engine-v1", "parameters": ["threshold": 0.3]]).write(to: file)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: .init(sourceSHA256: "other", engine: "engine-v1", parameters: ["threshold": "0.3"]), status: completed, artifactURL: file), .reuse)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: .init(sourceSHA256: "hash", engine: "engine-v1", parameters: ["threshold": "0.4"]), status: completed, artifactURL: file), .reuse)
    }

    func testArtifactHashCacheReusesAndInvalidatesByNanosecondMetadata() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let artifact = root.appendingPathComponent("raw.json"), statusURL = root.appendingPathComponent("processing-status.json")
        let fp = ResumeFingerprint(sourceSHA256: "hash", engine: "fake", parameters: [:])
        let hasher = CountingArtifactHasher(); var status = IntegratedProcessingStatus(sourcePath: "synthetic", sourceSHA256: "hash")
        let operation: @Sendable () async throws -> Void = { try Data("{\"schemaVersion\":1,\"sourceSHA256\":\"hash\",\"engine\":\"fake\",\"parameters\":{}}".utf8).write(to: artifact) }
        let didRun = await IntegratedModuleExecutor.execute(module: "m", fingerprint: fp, artifactURL: artifact, status: &status, statusURL: statusURL, hasher: hasher, operation: operation)
        XCTAssertTrue(didRun)
        let firstCount = hasher.calls.value
        XCTAssertGreaterThan(firstCount, 0)
        let reused = await IntegratedModuleExecutor.execute(module: "m", fingerprint: fp, artifactURL: artifact, status: &status, statusURL: statusURL, hasher: hasher, operation: operation)
        XCTAssertTrue(reused)
        XCTAssertEqual(hasher.calls.value, firstCount)
        let oldDate = Date(timeIntervalSince1970: 1_700_000_000.123456)
        try FileManager.default.setAttributes([.modificationDate: oldDate], ofItemAtPath: artifact.path)
        let changed = Data("{\"schemaVersion\":1,\"sourceSHA256\":\"hash\",\"engine\":\"fakx\",\"parameters\":{}}".utf8)
        try changed.write(to: artifact)
        try FileManager.default.setAttributes([.modificationDate: oldDate.addingTimeInterval(2)], ofItemAtPath: artifact.path)
        _ = await IntegratedModuleExecutor.execute(module: "m", fingerprint: fp, artifactURL: artifact, status: &status, statusURL: statusURL, hasher: hasher, operation: operation)
        XCTAssertGreaterThan(hasher.calls.value, firstCount)
    }

    func testStreamingResumeSkipsMultiMegabyteWindowsBeforeMetadata() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        let handle = try FileHandle(forWritingTo: createEmpty(file))
        try handle.write(contentsOf: Data("{\"windows\":[".utf8))
        let row = Data("{\"candidates\":[\"animal\",\"speech\",\"music\"]},".utf8)
        for i in 0..<80_000 { if i == 79_999 { try handle.write(contentsOf: Data(row.dropLast())) } else { try handle.write(contentsOf: row) } }
        try handle.write(contentsOf: Data("],\"schemaVersion\":1,\"sourceSHA256\":\"hash\",\"engine\":\"engine-v1\",\"parameters\":{}}".utf8)); try handle.close()
        let fp = ResumeFingerprint(sourceSHA256: "hash", engine: "engine-v1", parameters: [:])
        let status = IntegratedModuleStatus(state: "completed", fingerprint: fp)
        let start = Date()
        XCTAssertEqual(IntegratedModuleResumePlanner.plan(expected: fp, status: status, artifactURL: file), .reuse)
        XCTAssertLessThan(Date().timeIntervalSince(start), 10)
    }

    func testTruncationWithForgedUnchangedModificationTimeCannotReuse() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        let fp = ResumeFingerprint(sourceSHA256: "hash", engine: "engine-v1", parameters: [:])
        let bytes = Data("{\"schemaVersion\":1,\"sourceSHA256\":\"hash\",\"engine\":\"engine-v1\",\"parameters\":{}}".utf8)
        try bytes.write(to: file)
        let fixedDate = Date(timeIntervalSince1970: 1_700_000_000.123456)
        try FileManager.default.setAttributes([.modificationDate: fixedDate], ofItemAtPath: file.path)
        let cached = try ArtifactMetadata.fingerprint(file)
        try Data(bytes.prefix(bytes.count - 12)).write(to: file)
        try FileManager.default.setAttributes([.modificationDate: fixedDate], ofItemAtPath: file.path)
        let status = IntegratedModuleStatus(state: "completed", fingerprint: fp)
        XCTAssertNotEqual(IntegratedModuleResumePlanner.plan(expected: fp, status: status, artifactURL: file, cachedFingerprint: cached), .reuse)
    }

    private func createEmpty(_ url: URL) throws -> URL { _ = FileManager.default.createFile(atPath: url.path, contents: Data()); return url }

    func testCandidateTranscriptShowsUnmatchedAndAllAnonymousCandidates() {
        let entries = [
            SpeakerAlignedTranscriptEntry(startOffsetSeconds: 0, endOffsetSeconds: 1, absoluteStartLocal: "2026-01-01T00:00:00.000", absoluteEndLocal: "2026-01-01T00:00:01.000", speakerCandidates: [], hasUnattributedOverlap: false, text: "无候选"),
            SpeakerAlignedTranscriptEntry(startOffsetSeconds: 1, endOffsetSeconds: 2, absoluteStartLocal: "2026-01-01T00:00:01.000", absoluteEndLocal: "2026-01-01T00:00:02.000", speakerCandidates: ["speaker-2", "speaker-1"], hasUnattributedOverlap: true, text: "多候选"),
            SpeakerAlignedTranscriptEntry(startOffsetSeconds: 2, endOffsetSeconds: 3, absoluteStartLocal: "2026-01-01T00:00:02.000", absoluteEndLocal: "2026-01-01T00:00:03.000", speakerCandidates: [], hasUnattributedOverlap: true, text: "未知重叠")
        ]
        let doc = SpeakerAlignedTranscriptDocument(schemaVersion: 1, sourcePath: "synthetic", sourceSHA256: "hash", recordingStartLocal: "2026-01-01T00:00:00.000", transcriptionEngine: "test", diarizationEngine: "test", alignmentMethod: "overlap", accuracyAssessment: "not_evaluated", segments: entries)
        let md = UnifiedOutput.renderTranscript(doc, format: "md")
        XCTAssertTrue(md.contains("说话人候选：未匹配"))
        XCTAssertTrue(md.contains("speaker-1、speaker-2"))
        XCTAssertTrue(md.contains("speaker-1、speaker-2、未知"))
        XCTAssertTrue(md.contains("说话人候选：未知"))
        XCTAssertTrue(md.contains("2026-01-01T00:00:01.000"))
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
        let fingerprint = ResumeFingerprint(sourceSHA256: "source", engine: "engine-test", parameters: ["locale": "zh-CN"])
        let modules = ["speaker": IntegratedModuleStatus(state: "failed", error: "model missing", fingerprint: fingerprint), "transcription": IntegratedModuleStatus(state: "unsupported", error: "platform", fingerprint: fingerprint)]
        let manifest = try UnifiedOutput.buildManifest(inputPath: "synthetic.wav", sourceSHA256: "source", duration: 9, coverageRanges: [AudioTimeRange(startOffsetSeconds: 2, endOffsetSeconds: 4)], modules: modules, samples: ["sample": ["a", "b"]], artifactURLs: ["sample": artifact], baseDirectory: root, generatedAt: "fixed")
        XCTAssertEqual(manifest.inputPath, "synthetic.wav")
        XCTAssertEqual(manifest.sourceSHA256, "source")
        XCTAssertEqual(manifest.generatedAt, "fixed")
        XCTAssertEqual(manifest.modules["speaker"]?.error, "model missing")
        XCTAssertEqual(manifest.modules["speaker"]?.fingerprint, fingerprint)
        XCTAssertEqual(manifest.modules["transcription"]?.state, "unsupported")
        XCTAssertEqual(manifest.artifacts["sample"]?.path, "sample.json")
        XCTAssertEqual(manifest.artifacts["sample"]?.sha256, SHA256.digest(Data("synthetic".utf8)))
        XCTAssertEqual(manifest.coverage?.coveredSeconds, 2)
        XCTAssertEqual(manifest.samples["sample"]?.first, ["a", "b"])
    }

    func testWrittenManifestHashesMatchFinalArtifactsAndExcludeMutableStatus() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let statusURL = root.appendingPathComponent("processing-status.json")
        let artifactURL = root.appendingPathComponent("sample.json")
        let manifestURL = root.appendingPathComponent("run-manifest.json")
        try Data("initial status".utf8).write(to: statusURL)
        try Data("final artifact".utf8).write(to: artifactURL)

        let manifest = try UnifiedOutput.writeManifest(
            inputPath: "synthetic.wav", sourceSHA256: "source", duration: nil, coverageRanges: [],
            modules: [:], samples: [:],
            artifactURLs: ["sample": artifactURL, "sample-alias": artifactURL, "processing-status": statusURL],
            baseDirectory: root, to: manifestURL, generatedAt: "fixed")

        // This is the CLI's post-write completed record; changing it must not stale any listed hash.
        var status = IntegratedProcessingStatus(sourcePath: "synthetic.wav", sourceSHA256: "source")
        status.record("runManifest", state: "completed")
        try AtomicFile.write(try JSONEncoder().encode(status), to: statusURL)

        let onDisk = try JSONDecoder().decode(RunManifest.self, from: Data(contentsOf: manifestURL))
        XCTAssertEqual(onDisk, manifest)
        XCTAssertEqual(onDisk.artifacts.count, 1)
        XCTAssertEqual(onDisk.artifacts["sample"]?.path, "sample.json")
        XCTAssertFalse(onDisk.artifacts.values.contains { $0.path == "processing-status.json" })
        XCTAssertEqual(Set(onDisk.artifacts.values.map(\.path)).count, onDisk.artifacts.count)
        for record in onDisk.artifacts.values {
            let artifact = root.appendingPathComponent(record.path)
            XCTAssertEqual(try SHA256.file(artifact), record.sha256, "hash mismatch for \(record.path)")
        }
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

    func testInjectedENOSPCMarksModuleFailedAndStillWritesManifest() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        var status = IntegratedProcessingStatus(sourcePath: "synthetic", sourceSHA256: "hash")
        let artifact = root.appendingPathComponent("blocked.json"), statusURL = root.appendingPathComponent("processing-status.json")
        let fp = ResumeFingerprint(sourceSHA256: "hash", engine: "synthetic", parameters: [:])
        let completed = await IntegratedModuleExecutor.execute(module: "writer", fingerprint: fp, status: &status, statusURL: statusURL) {
            try AtomicFile.write(Data("x".utf8), to: artifact, using: ENOSPCWriter())
        }
        XCTAssertFalse(completed)
        XCTAssertEqual(status.modules["writer"]?.state, "failed")
        XCTAssertTrue(status.modules["writer"]?.error?.contains("磁盘空间不足") == true)
        let manifestURL = root.appendingPathComponent("run-manifest.json")
        _ = try UnifiedOutput.writeManifest(inputPath: "synthetic.wav", sourceSHA256: "hash", duration: nil, coverageRanges: [], modules: status.modules, samples: [:], artifactURLs: [:], baseDirectory: root, to: manifestURL)
        XCTAssertTrue(FileManager.default.fileExists(atPath: manifestURL.path))
        let saved = try JSONDecoder().decode(IntegratedProcessingStatus.self, from: Data(contentsOf: statusURL))
        XCTAssertEqual(saved.modules["writer"]?.state, "failed")
    }

    func testArtifactWriteFailureCanBeRecordedWithReason() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let blocker = root.appendingPathComponent("blocked")
        try Data().write(to: blocker)
        var status = IntegratedProcessingStatus(sourcePath: "synthetic", sourceSHA256: "hash")
        let target = blocker.appendingPathComponent("transcript.md")
        let statusURL = root.appendingPathComponent("status.json")
        let entry = SpeakerAlignedTranscriptEntry(startOffsetSeconds: 0, endOffsetSeconds: 1, absoluteStartLocal: "2026-01-01T00:00:00.000", absoluteEndLocal: "2026-01-01T00:00:01.000", speakerCandidates: [], hasUnattributedOverlap: false, text: "test")
        let doc = SpeakerAlignedTranscriptDocument(schemaVersion: 1, sourcePath: "synthetic", sourceSHA256: "hash", recordingStartLocal: entry.absoluteStartLocal, transcriptionEngine: "test", diarizationEngine: "test", alignmentMethod: "overlap", accuracyAssessment: "not_evaluated", segments: [entry])
        XCTAssertThrowsError(try UnifiedOutput.writeTranscript(doc, format: "md", to: target, status: &status, statusURL: statusURL, fingerprint: ResumeFingerprint(sourceSHA256: "hash", engine: "renderer", parameters: ["format": "md"])))
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

    private func mp3Frame(xingFrames: UInt32? = nil, vbriFrames: UInt32? = nil, version: Int = 3, mono: Bool = false, crc: Bool = false) -> Data {
        let header: [UInt8] = version == 3 ? [0xff, 0xfb, 0x90, mono ? 0xc0 : 0] : (version == 2 ? [0xff, 0xf3, 0x80, mono ? 0xc0 : 0] : [0xff, 0xe3, 0x80, mono ? 0xc0 : 0])
        let bitrate = version == 3 ? 128_000 : 64_000
        let rate = version == 3 ? 44_100 : version == 2 ? 22_050 : 11_025
        let length = (version == 3 ? 144 : 72) * bitrate / rate
        var frame = Data(header) + Data(repeating: 0, count: length - 4)
        if crc { frame[1] &= 0xfe; frame.replaceSubrange(4..<4, with: [0, 0]); frame.removeLast(2) }
        if let xingFrames {
            frame.replaceSubrange(36..<40, with: Data("Xing".utf8))
            frame[43] = 1
            frame[44] = UInt8((xingFrames >> 24) & 0xff); frame[45] = UInt8((xingFrames >> 16) & 0xff)
            frame[46] = UInt8((xingFrames >> 8) & 0xff); frame[47] = UInt8(xingFrames & 0xff)
        }
        if let vbriFrames {
            frame.replaceSubrange(36..<40, with: Data("VBRI".utf8))
            frame[50] = UInt8((vbriFrames >> 24) & 0xff); frame[51] = UInt8((vbriFrames >> 16) & 0xff)
            frame[52] = UInt8((vbriFrames >> 8) & 0xff); frame[53] = UInt8(vbriFrames & 0xff)
        }
        return frame
    }

    func testSyntheticMP3VBRFileReturnsFromPrefixAndHashFileMatchesData() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("synthetic.mp3")
        let bytes = mp3Frame(xingFrames: 100) + Data(repeating: 0, count: 8 * 1024 * 1024)
        try bytes.write(to: url)
        let result = try UnifiedOutput.audioDuration(file: url)
        XCTAssertEqual(result.method, "xing")
        XCTAssertEqual(result.seconds ?? 0, 100 * 1152.0 / 44100.0, accuracy: 0.000001)
        XCTAssertEqual(try SHA256.file(url), SHA256.digest(bytes))
    }

    func testSyntheticMP3MPEG2MPEG25CRCAndMonoFrames() {
        for (version, expected) in [(2, 2 * 576.0 / 22050.0), (0, 2 * 576.0 / 11025.0)] {
            let result = UnifiedOutput.audioDuration(data: mp3Frame(version: version, mono: true, crc: true) + mp3Frame(version: version, mono: true, crc: true))
            XCTAssertEqual(result.seconds ?? 0, expected, accuracy: 0.000001)
        }
    }

    func testSyntheticMP3CBRFrameScanAndID3v2() {
        let cbr = mp3Frame() + mp3Frame() + mp3Frame()
        let result = UnifiedOutput.audioDuration(data: cbr)
        XCTAssertEqual(result.seconds ?? 0, 3 * 1152.0 / 44100.0, accuracy: 0.000001)
        XCTAssertEqual(result.method, "frame-scan")
        var tagged = Data("ID3".utf8) + Data([4, 0, 0, 0, 0, 0, 3]) + Data([1, 2, 3])
        tagged.append(cbr)
        XCTAssertEqual(UnifiedOutput.audioDuration(data: tagged).method, "frame-scan")
        XCTAssertEqual(UnifiedOutput.audioDuration(data: tagged).seconds ?? 0, result.seconds ?? -1, accuracy: 0.000001)
    }

    func testMP3FrameScanCompensatesCumulativeFloatingPointError() {
        let frameCount = 100_000
        let frame = mp3Frame(version: 2)
        var data = Data(capacity: frame.count * frameCount)
        for _ in 0..<frameCount { data.append(frame) }

        let result = UnifiedOutput.audioDuration(data: data)
        XCTAssertEqual(result.method, "frame-scan")
        XCTAssertEqual(result.seconds ?? 0, Double(frameCount) * 576.0 / 22_050.0, accuracy: 1e-10)
    }

    func testSyntheticMP3ID3v1AndTrailingGarbageKeepScannedDuration() {
        let frames = mp3Frame() + mp3Frame()
        let tagged = UnifiedOutput.audioDuration(data: frames + Data("TAG".utf8) + Data(repeating: 0, count: 125))
        XCTAssertEqual(tagged.seconds ?? 0, 2 * 1152.0 / 44100.0, accuracy: 0.000001)
        XCTAssertTrue(tagged.method.contains("ID3v1"))
        let garbage = UnifiedOutput.audioDuration(data: frames + Data([0xde, 0xad, 0xbe]))
        XCTAssertEqual(garbage.seconds ?? 0, 2 * 1152.0 / 44100.0, accuracy: 0.000001)
        XCTAssertTrue(garbage.method.contains("garbage"))
    }

    func testSyntheticMP3XingAndInvalidInputs() {
        let data = mp3Frame(xingFrames: 100) + mp3Frame()
        let result = UnifiedOutput.audioDuration(data: data)
        XCTAssertEqual(result.method, "xing")
        XCTAssertEqual(result.seconds ?? 0, 100 * 1152.0 / 44100.0, accuracy: 0.000001)
        let truncated = Data([0xff, 0xfb, 0x90, 0x00])
        XCTAssertNil(UnifiedOutput.audioDuration(data: truncated).seconds)
        XCTAssertEqual(UnifiedOutput.audioDuration(data: truncated).method, "failed")
        let garbage = UnifiedOutput.audioDuration(data: Data("synthetic garbage".utf8))
        XCTAssertNil(garbage.seconds)
        XCTAssertEqual(garbage.method, "unsupported")
        XCTAssertFalse(garbage.error?.isEmpty ?? true)
        let vbri = UnifiedOutput.audioDuration(data: mp3Frame(vbriFrames: 80))
        XCTAssertEqual(vbri.method, "vbri")
        XCTAssertEqual(vbri.seconds ?? 0, 80 * 1152.0 / 44100.0, accuracy: 0.000001)
    }

    func testSyntheticM4AMVHDDuration() {
        func u32(_ value: UInt32) -> Data { Data([UInt8(value >> 24), UInt8((value >> 16) & 255), UInt8((value >> 8) & 255), UInt8(value & 255)]) }
        func atom(_ type: String, _ payload: Data) -> Data { u32(UInt32(payload.count + 8)) + Data(type.utf8) + payload }
        let mvhd = Data(repeating: 0, count: 12) + u32(1000) + u32(12_345) + Data(repeating: 0, count: 20)
        let data = atom("ftyp", Data("M4A ".utf8) + Data(repeating: 0, count: 8)) + atom("moov", atom("mvhd", mvhd))
        let result = UnifiedOutput.audioDuration(data: data)
        XCTAssertEqual(try XCTUnwrap(result.seconds), 12.345, accuracy: 0.000001)
        XCTAssertEqual(result.method, "mvhd/mdhd")
    }

    func testSyntheticM4ARejectsOverflowingLargeAtomSize() {
        let bytes = Data([0,0,0,1]) + Data("moov".utf8) + Data(repeating: 0xff, count: 8)
        let result = UnifiedOutput.audioDuration(data: bytes)
        XCTAssertNil(result.seconds)
        XCTAssertEqual(result.method, "failed")
        XCTAssertFalse(result.error?.isEmpty ?? true)
    }

    func testPerformanceFieldsAndUnitsSerialize() throws {
        let sample = ProcessPeakMemory.current()
        let perf = RunPerformance(wallClockSeconds: 1.25, peakMemoryBytes: sample.bytes, peakMemorySource: sample.source, ruMaxRSSUnit: sample.unit)
        let manifest = try UnifiedOutput.buildManifest(inputPath: "synthetic.mp3", sourceSHA256: "hash", duration: 1, coverageRanges: [], modules: ["m": IntegratedModuleStatus(state: "completed", wallClockSeconds: 0.25, execution: "recomputed")], samples: [:], artifactURLs: [:], baseDirectory: FileManager.default.temporaryDirectory, performance: perf)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(manifest)) as? [String: Any])
        let encodedPerformance = try XCTUnwrap(object["performance"] as? [String: Any])
        XCTAssertTrue(encodedPerformance["wallClockSeconds"] is NSNumber)
        XCTAssertTrue(encodedPerformance["peakMemoryBytes"] is NSNumber)
        #if os(Linux)
        XCTAssertEqual(encodedPerformance["ruMaxRSSUnit"] as? String, "KB")
        #elseif os(macOS)
        XCTAssertEqual(encodedPerformance["ruMaxRSSUnit"] as? String, "bytes")
        #endif
        XCTAssertEqual(manifest.modules["m"]?.execution, "recomputed")
        XCTAssertNotNil(manifest.modules["m"]?.wallClockSeconds)
        let unknownDuration = try UnifiedOutput.buildManifest(inputPath: "bad.mp3", sourceSHA256: "hash", duration: nil, coverageRanges: [], modules: [:], samples: [:], artifactURLs: [:], baseDirectory: FileManager.default.temporaryDirectory, durationMethod: "failed", durationError: "truncated")
        let unknownJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(unknownDuration)) as? [String: Any])
        XCTAssertTrue(unknownJSON["audioDurationSeconds"] is NSNull)
        XCTAssertTrue(unknownJSON["coverage"] is NSNull)
        XCTAssertEqual(unknownJSON["durationError"] as? String, "truncated")
    }
}
