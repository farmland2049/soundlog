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
        XCTAssertNil(library.match(vector: [1, 0], minimumRawSimilarity: 0.8).identityID)
        try library.confirm(id, name: "Alice")
        XCTAssertEqual(library.match(vector: [1, 0], minimumRawSimilarity: 0.8).displayName, "Alice")
    }
    func testUnknownWhenBelowThresholdOrNoConfirmedIdentity() throws {
        var library = IdentityLibrary(); let id = library.add(try enrollment([1, 0])); try library.confirm(id, name: "Alice")
        XCTAssertNil(library.match(vector: [0, 1], minimumRawSimilarity: 0.8).identityID)
    }
    func testSplitMergeRenameAndRevokeHistory() throws {
        var library = IdentityLibrary(); let first = library.add(try enrollment([1, 0])); try library.confirm(first, name: "Alice")
        let second = try library.split(first, into: enrollment([0.9, 0.1]))
        try library.confirm(second, name: "Bob")
        try library.rename(second, to: "Bobby")
        try library.merge(second, into: first)
        XCTAssertTrue(library.enrollments.first(where: { $0.id == second })!.revoked)
        try library.revoke(first, reason: "synthetic mistaken match")
        XCTAssertNil(library.match(vector: [1, 0], minimumRawSimilarity: -1).identityID)
        XCTAssertTrue(library.enrollments.first(where: { $0.id == first })!.history.map(\.action).contains(.split))
        XCTAssertTrue(library.enrollments.first(where: { $0.id == first })!.history.map(\.action).contains(.merged))
        XCTAssertTrue(library.enrollments.first(where: { $0.id == first })!.history.map(\.action).contains(.revoked))
        XCTAssertTrue(library.enrollments.first(where: { $0.id == second })!.history.map(\.action).contains(.renamed))
    }
    func testSplitEnrollmentRequiresExplicitConfirmation() throws {
        var library = IdentityLibrary()
        let parent = library.add(try enrollment([1, 0]))
        let child = try library.split(parent, into: enrollment([0.9, 0.1]))

        let matchBeforeConfirm = library.match(vector: [0.9, 0.1], minimumRawSimilarity: 0.8)
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
        let match = library.match(vector: [0.9, 0.1], minimumRawSimilarity: 0.8)
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
        let match = library.match(vector: [1, 0], minimumRawSimilarity: 0)
        XCTAssertEqual(match.rawSimilarityScore, 1)
        XCTAssertEqual(match.scoreMeaning, "raw_similarity_not_probability")
    }
}
