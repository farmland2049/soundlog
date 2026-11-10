import XCTest
@testable import SoundlogCore

final class IdentityMatchTests: XCTestCase {
    private func enrollment(_ vector: [Float], name: String? = nil) throws -> IdentityEnrollment {
        let sample = try IdentitySampleReference(sourcePath: "/synthetic/audio.wav", startOffsetSeconds: 1, endOffsetSeconds: 2, sourceSHA256: "synthetic-hash")
        return IdentityEnrollment(displayName: name, confirmed: name != nil, samples: [sample], embedding: vector,
                                  basis: "user-reviewed synthetic sample", modelVersion: "test-model", engineVersion: "test-engine")
    }
    func testNameRequiresExplicitConfirmation() throws {
        var library = IdentityLibrary(); let id = library.add(try enrollment([1, 0], name: "Alice"))
        XCTAssertNil(library.enrollments[0].displayName)
        XCTAssertNil(try library.match(vector: [1, 0], minimumRawSimilarity: 0.8).identityID)
        try library.confirm(id, name: "Alice")
        XCTAssertEqual(try library.match(vector: [1, 0], minimumRawSimilarity: 0.8).displayName, "Alice")
    }
    func testUnknownWhenBelowThresholdOrNoConfirmedIdentity() throws {
        var library = IdentityLibrary(); let id = library.add(try enrollment([1, 0])); try library.confirm(id, name: "Alice")
        XCTAssertNil(try library.match(vector: [0, 1], minimumRawSimilarity: 0.8).identityID)
    }
    func testSplitMergeRenameAndRevokeHistory() throws {
        var library = IdentityLibrary(); let first = library.add(try enrollment([1, 0])); try library.confirm(first, name: "Alice")
        let second = try library.split(first, into: enrollment([0.9, 0.1]))
        try library.confirm(second, name: "Bob")
        try library.rename(second, to: "Bobby")
        try library.merge(second, into: first)
        XCTAssertTrue(library.enrollments.first(where: { $0.id == second })!.revoked)
        try library.revoke(first, reason: "synthetic mistaken match")
        XCTAssertNil(try library.match(vector: [1, 0], minimumRawSimilarity: -1).identityID)
        XCTAssertTrue(library.enrollments.first(where: { $0.id == first })!.history.map(\.action).contains(.split))
        XCTAssertTrue(library.enrollments.first(where: { $0.id == first })!.history.map(\.action).contains(.merged))
        XCTAssertTrue(library.enrollments.first(where: { $0.id == first })!.history.map(\.action).contains(.revoked))
        XCTAssertTrue(library.enrollments.first(where: { $0.id == second })!.history.map(\.action).contains(.renamed))
    }
    func testSplitEnrollmentRequiresExplicitConfirmation() throws {
        var library = IdentityLibrary()
        let parent = library.add(try enrollment([1, 0]))
        let child = try library.split(parent, into: enrollment([0.9, 0.1]))

        let matchBeforeConfirm = try library.match(vector: [0.9, 0.1], minimumRawSimilarity: 0.8)
        XCTAssertNil(matchBeforeConfirm.identityID)
        XCTAssertNil(matchBeforeConfirm.displayName)
        XCTAssertEqual(library.enrollments.first(where: { $0.id == child })?.history.last?.action, .split)
    }
    func testSplitSanitizesPrefilledConfirmationAndHistory() throws {
        var library = IdentityLibrary()
        let parent = library.add(try enrollment([1, 0]))
        let supplied = try enrollment([0.9, 0.1], name: "Mallory")
        let child = try library.split(parent, into: supplied)

        let stored = try XCTUnwrap(library.enrollments.first(where: { $0.id == child }))
        XCTAssertFalse(stored.confirmed)
        XCTAssertNil(stored.displayName)
        XCTAssertFalse(stored.history.contains(where: { $0.action == .confirmed }))
        let match = try library.match(vector: [0.9, 0.1], minimumRawSimilarity: 0.8)
        XCTAssertNil(match.identityID)
        XCTAssertNil(match.displayName)
    }
    func testRenameRequiresConfirmationAndUpdatesConfirmedName() throws {
        var library = IdentityLibrary()
        let pendingID = library.add(try enrollment([1, 0]))
        XCTAssertThrowsError(try library.rename(pendingID, to: "Alice"))

        try library.confirm(pendingID, name: "Alice")
        try library.rename(pendingID, to: "Alicia")
        XCTAssertEqual(library.enrollments.first(where: { $0.id == pendingID })?.displayName, "Alicia")
    }
    func testSimilarityIsNamedRawScoreNotProbability() throws {
        var library = IdentityLibrary(); let id = library.add(try enrollment([1, 0])); try library.confirm(id, name: "Alice")
        let match = try library.match(vector: [1, 0], minimumRawSimilarity: 0)
        XCTAssertEqual(match.rawSimilarityScore, 1)
        XCTAssertEqual(match.scoreMeaning, "raw_similarity_not_probability")
    }

    private func createTestWAV(seconds: Double = 1.0) throws -> URL {
        let sampleRate: UInt32 = 16000
        let numChannels: UInt16 = 1
        let bitsPerSample: UInt16 = 16
        let byteRate = sampleRate * UInt32(numChannels) * UInt32(bitsPerSample / 8)
        let blockAlign = numChannels * (bitsPerSample / 8)
        let totalSamples = UInt32(Double(sampleRate) * seconds)
        let dataSize = totalSamples * UInt32(blockAlign)
        let chunkSize = 36 + dataSize

        var data = Data()
        data.append(contentsOf: "RIFF".utf8)
        withUnsafeBytes(of: chunkSize.littleEndian) { data.append(contentsOf: $0) }
        data.append(contentsOf: "WAVE".utf8)
        data.append(contentsOf: "fmt ".utf8)
        let subchunk1Size: UInt32 = 16
        withUnsafeBytes(of: subchunk1Size.littleEndian) { data.append(contentsOf: $0) }
        let audioFormat: UInt16 = 1
        withUnsafeBytes(of: audioFormat.littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: numChannels.littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: sampleRate.littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: byteRate.littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: blockAlign.littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: bitsPerSample.littleEndian) { data.append(contentsOf: $0) }
        data.append(contentsOf: "data".utf8)
        withUnsafeBytes(of: dataSize.littleEndian) { data.append(contentsOf: $0) }
        data.append(Data(repeating: 0, count: Int(dataSize)))

        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        let fileURL = tempDir.appendingPathComponent("20261110120000.wav")
        try data.write(to: fileURL)
        return fileURL
    }

    func testMockSpeakerEmbeddingExtractorDeterminism() async throws {
        let wav = try createTestWAV(seconds: 2.0)
        let extractor = MockSpeakerEmbeddingExtractor()
        XCTAssertTrue(extractor.identifier.contains("mock"))

        let segments = [
            SpeakerTimelineEntry(speakerID: "SPEAKER_00", startOffsetSeconds: 0, endOffsetSeconds: 1, absoluteStartLocal: "12:00:00", absoluteEndLocal: "12:00:01"),
            SpeakerTimelineEntry(speakerID: "SPEAKER_01", startOffsetSeconds: 1, endOffsetSeconds: 2, absoluteStartLocal: "12:00:01", absoluteEndLocal: "12:00:02")
        ]

        let result1 = try await extractor.extractEmbeddings(file: wav, segments: segments)
        let result2 = try await extractor.extractEmbeddings(file: wav, segments: segments)

        XCTAssertEqual(result1.count, 2)
        XCTAssertEqual(result1, result2)

        let emb0 = result1.first(where: { $0.speakerID == "SPEAKER_00" })!
        let emb1 = result1.first(where: { $0.speakerID == "SPEAKER_01" })!
        XCTAssertEqual(emb0.embedding.count, 256)
        XCTAssertEqual(emb1.embedding.count, 256)
        XCTAssertNotEqual(emb0.embedding, emb1.embedding)

        let norm0 = sqrt(emb0.embedding.reduce(0.0) { $0 + Double($1 * $1) })
        XCTAssertEqual(norm0, 1.0, accuracy: 0.001)
    }

    func testMatchConfirmedSyntheticIdentityHits() throws {
        var library = IdentityLibrary()
        let fakeVector: [Float] = (0..<256).map { i in Float(sin(Double(i))) }
        let norm = sqrt(fakeVector.reduce(0.0) { $0 + Double($1 * $1) })
        let normalizedVector = fakeVector.map { Float(Double($0) / norm) }

        let sample = try IdentitySampleReference(sourcePath: "/synthetic/test.wav", startOffsetSeconds: 0, endOffsetSeconds: 1, sourceSHA256: "fake-sha256")
        let enrollment = IdentityEnrollment(
            displayName: "SyntheticSpeakerA",
            confirmed: true,
            samples: [sample],
            embedding: normalizedVector,
            basis: "synthetic test sample",
            modelVersion: "mock-model",
            engineVersion: "mock-engine"
        )
        let id = library.add(enrollment)
        try library.confirm(id, name: "SyntheticSpeakerA")

        let match = try library.match(vector: normalizedVector, minimumRawSimilarity: 0.8)
        XCTAssertEqual(match.displayName, "SyntheticSpeakerA")
        XCTAssertEqual(match.identityID, id)
        XCTAssertNotNil(match.rawSimilarityScore)
        if let score = match.rawSimilarityScore {
            XCTAssertGreaterThanOrEqual(score, 0.99)
        }
    }

    func testMatchEmptyLibraryReturnsUnknown() throws {
        let library = IdentityLibrary()
        let vector: [Float] = [0.1, 0.2, 0.3]
        let match = try library.match(vector: vector, minimumRawSimilarity: 0.5)
        XCTAssertNil(match.identityID)
        XCTAssertNil(match.displayName)
        XCTAssertEqual(match.scoreMeaning, "raw_similarity_not_probability")
    }

    func testMatchDimensionMismatchThrowsIncompatibleVectors() throws {
        var library = IdentityLibrary()
        let id = library.add(try enrollment([1, 0], name: "Alice"))
        try library.confirm(id, name: "Alice")

        // Library has 2-dim confirmed vector, query has 3-dim vector
        XCTAssertThrowsError(try library.match(vector: [0.1, 0.2, 0.3], minimumRawSimilarity: 0.5)) { error in
            XCTAssertEqual(error as? IdentityLibraryError, IdentityLibraryError.incompatibleVectors)
        }
    }
}
