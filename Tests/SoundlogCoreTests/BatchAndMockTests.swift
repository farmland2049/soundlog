import XCTest
@testable import SoundlogCore

final class BatchAndMockTests: XCTestCase {
    private func createValidWAV(at url: URL, durationSeconds: Double = 1.0) throws {
        let sampleRate: UInt32 = 16000
        let channels: UInt16 = 1
        let bitsPerSample: UInt16 = 16
        let byteRate = sampleRate * UInt32(channels) * UInt32(bitsPerSample / 8)
        let blockAlign = channels * (bitsPerSample / 8)
        let sampleCount = UInt32(Double(sampleRate) * durationSeconds)
        let dataSize = sampleCount * UInt32(blockAlign)
        let chunkSize = 36 + dataSize

        var data = Data()
        data.append(contentsOf: "RIFF".utf8)
        data.append(contentsOf: withUnsafeBytes(of: chunkSize.littleEndian) { Array($0) })
        data.append(contentsOf: "WAVE".utf8)
        data.append(contentsOf: "fmt ".utf8)
        data.append(contentsOf: withUnsafeBytes(of: UInt32(16).littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: UInt16(1).littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: channels.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: sampleRate.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: byteRate.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: blockAlign.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: bitsPerSample.littleEndian) { Array($0) })
        data.append(contentsOf: "data".utf8)
        data.append(contentsOf: withUnsafeBytes(of: dataSize.littleEndian) { Array($0) })
        data.append(Data(repeating: 0, count: Int(dataSize)))

        try data.write(to: url)
    }

    func testMockEnginesSucceedOnValidWAVAndFailOnCorruptedFile() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let validWav = root.appendingPathComponent("20261110120000.wav")
        try createValidWAV(at: validWav, durationSeconds: 2.5)

        let corruptWav = root.appendingPathComponent("20261110130000.wav")
        try Data([0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03]).write(to: corruptWav)

        let mockTrans = MockTranscriptionEngine()
        XCTAssertTrue(mockTrans.identifier.contains("mock"))
        let transResult = try await mockTrans.transcribe(file: validWav)
        XCTAssertFalse(transResult.segments.isEmpty)
        XCTAssertFalse(transResult.coveredRanges.isEmpty)
        XCTAssertEqual(transResult.coveredRanges.first?.endOffsetSeconds, 2.5)
        do {
            _ = try await mockTrans.transcribe(file: corruptWav)
            XCTFail("Corrupt wav should throw in mock transcription")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Mock"))
        }

        let mockSound = MockSoundEventEngine()
        XCTAssertTrue(mockSound.identifier.contains("mock"))
        let soundResult = try await mockSound.classify(file: validWav)
        XCTAssertFalse(soundResult.windows.isEmpty)
        do {
            _ = try await mockSound.classify(file: corruptWav)
            XCTFail("Corrupt wav should throw in mock sound event")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Mock"))
        }

        let mockSpeaker = MockSpeakerDiarizationEngine()
        XCTAssertTrue(mockSpeaker.identifier.contains("mock"))
        let speakerResult = try await mockSpeaker.diarize(file: validWav)
        XCTAssertEqual(speakerResult.segments.count, 1)
        XCTAssertEqual(speakerResult.segments.first?.endOffsetSeconds, 2.5)
        do {
            _ = try await mockSpeaker.diarize(file: corruptWav)
            XCTFail("Corrupt wav should throw in mock diarization")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Mock"))
        }
    }

    func testBatchAcceptanceReportEvaluation() {
        var completedModules: [String: IntegratedModuleStatus] = [:]
        for name in [
            "transcription",
            "soundEvents",
            "speakerDiarization",
            "speakerAlignment",
            "unifiedTranscript",
            "inputCoverage",
            "runManifest"
        ] {
            completedModules[name] = IntegratedModuleStatus(state: "completed", fingerprint: ResumeFingerprint(sourceSHA256: "h", engine: "e", parameters: [:]))
        }

        let successEval = BatchAcceptanceReport.evaluateFileStatus(modules: completedModules)
        XCTAssertEqual(successEval.status, "completed")
        XCTAssertNil(successEval.failureReason)

        var failingModules = completedModules
        failingModules["transcription"] = IntegratedModuleStatus(state: "failed", error: "Decode error", fingerprint: ResumeFingerprint(sourceSHA256: "h", engine: "e", parameters: [:]))
        failingModules["speakerAlignment"] = IntegratedModuleStatus(state: "skipped", error: "Prerequisite not met", fingerprint: ResumeFingerprint(sourceSHA256: "h", engine: "e", parameters: [:]))

        let failEval = BatchAcceptanceReport.evaluateFileStatus(modules: failingModules)
        XCTAssertEqual(failEval.status, "failed")
        XCTAssertNotNil(failEval.failureReason)
        XCTAssertTrue(failEval.failureReason?.contains("transcription: failed") == true)
        XCTAssertTrue(failEval.failureReason?.contains("speakerAlignment: skipped") == true)
    }

    func testBatchAcceptanceReportSerialization() throws {
        let report = BatchAcceptanceReport(
            runTime: "2026-11-10T12:00:00Z",
            inputPath: "/tmp/test",
            isMock: true,
            totalFiles: 2,
            successCount: 1,
            failureCount: 1,
            files: [
                BatchAcceptanceReport.FileRecord(path: "/tmp/test/f1.wav", status: "completed", failureReason: nil, modules: ["transcription": "completed"]),
                BatchAcceptanceReport.FileRecord(path: "/tmp/test/f2.wav", status: "failed", failureReason: "Corrupted", modules: ["transcription": "failed"])
            ]
        )
        let data = try JSONEncoder().encode(report)
        let decoded = try JSONDecoder().decode(BatchAcceptanceReport.self, from: data)
        XCTAssertEqual(report, decoded)
        XCTAssertEqual(decoded.totalFiles, 2)
        XCTAssertEqual(decoded.successCount, 1)
        XCTAssertEqual(decoded.failureCount, 1)
        XCTAssertTrue(decoded.isMock)
        XCTAssertFalse(decoded.successDefinition.isEmpty)
    }

    func testCLIProcessBatchWithMockModeAndCorruptFile() throws {
        let cliURL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent(".build/debug/SoundlogCLI")
        guard FileManager.default.isExecutableFile(atPath: cliURL.path) else { return }

        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let inputDir = tempDir.appendingPathComponent("input", isDirectory: true)
        let outputDir = tempDir.appendingPathComponent("output", isDirectory: true)
        let runDir = outputDir.appendingPathComponent("run", isDirectory: true)
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let goodWav = inputDir.appendingPathComponent("20261110120000.wav")
        try createValidWAV(at: goodWav, durationSeconds: 1.0)

        let badWav = inputDir.appendingPathComponent("20261110130000.wav")
        try Data([0xDE, 0xAD, 0xBE, 0xEF]).write(to: badWav)

        let process = Process()
        process.executableURL = cliURL
        process.arguments = [
            "process",
            "--input", inputDir.path,
            "--output-dir", outputDir.path,
            "--run-dir", runDir.path,
            "--param", "engines=mock"
        ]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        process.waitUntilExit()

        XCTAssertEqual(process.terminationStatus, 1)

        let reportURL = runDir.appendingPathComponent("记录/整理验收.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: reportURL.path))
        let reportData = try Data(contentsOf: reportURL)
        let report = try JSONDecoder().decode(BatchAcceptanceReport.self, from: reportData)

        XCTAssertEqual(report.totalFiles, 2)
        XCTAssertEqual(report.successCount, 1)
        XCTAssertEqual(report.failureCount, 1)
        XCTAssertTrue(report.isMock)

        let goodRecord = report.files.first { $0.path == goodWav.path }
        XCTAssertEqual(goodRecord?.status, "completed")
        XCTAssertNil(goodRecord?.failureReason)

        let badRecord = report.files.first { $0.path == badWav.path }
        XCTAssertEqual(badRecord?.status, "failed")
        XCTAssertNotNil(badRecord?.failureReason)
    }
}
