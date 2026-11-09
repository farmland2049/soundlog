import Foundation

/// A pointer to audio already present on the user's machine. It contains no audio or embedding.
public struct IdentitySampleReference: Codable, Equatable, Sendable {
    public let sourcePath: String
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double
    public let sourceSHA256: String

    public init(sourcePath: String, startOffsetSeconds: Double, endOffsetSeconds: Double, sourceSHA256: String) throws {
        _ = try AudioTimeRange(startOffsetSeconds: startOffsetSeconds, endOffsetSeconds: endOffsetSeconds)
        guard !sourcePath.isEmpty, !sourceSHA256.isEmpty else { throw IdentityLibraryError.invalidSample }
        self.sourcePath = sourcePath
        self.startOffsetSeconds = startOffsetSeconds
        self.endOffsetSeconds = endOffsetSeconds
        self.sourceSHA256 = sourceSHA256
    }
}

public enum IdentityHistoryAction: String, Codable, Sendable { case created, confirmed, split, merged, renamed, revoked }
public struct IdentityHistoryEntry: Codable, Equatable, Sendable {
    public let action: IdentityHistoryAction
    public let date: String
    public let detail: String
    public init(action: IdentityHistoryAction, date: String = ISO8601DateFormatter().string(from: Date()), detail: String) {
        self.action = action; self.date = date; self.detail = detail
    }
}

public struct IdentityEnrollment: Codable, Equatable, Sendable {
    public let id: UUID
    public var displayName: String?
    public var confirmed: Bool
    public var revoked: Bool
    public var samples: [IdentitySampleReference]
    /// Synthetic/test-friendly raw feature vector; never calibrated as a probability.
    public var embedding: [Float]
    public let basis: String
    public let modelVersion: String
    public let engineVersion: String
    public var history: [IdentityHistoryEntry]

    public init(id: UUID = UUID(), displayName: String? = nil, confirmed: Bool = false,
                samples: [IdentitySampleReference], embedding: [Float], basis: String,
                modelVersion: String, engineVersion: String) {
        self.id = id; self.displayName = displayName; self.confirmed = confirmed; self.revoked = false
        self.samples = samples; self.embedding = embedding; self.basis = basis
        self.modelVersion = modelVersion; self.engineVersion = engineVersion
        self.history = [IdentityHistoryEntry(action: .created, detail: basis)]
    }
}

public struct IdentityMatch: Codable, Equatable, Sendable {
    public let identityID: UUID?
    public let displayName: String?
    public let rawSimilarityScore: Double?
    public let scoreMeaning: String
    public static func unknown(bestScore: Double? = nil) -> IdentityMatch {
        IdentityMatch(identityID: nil, displayName: nil, rawSimilarityScore: bestScore,
                      scoreMeaning: "raw_similarity_not_probability")
    }
}

public enum IdentityLibraryError: Error, Equatable { case invalidSample, missingIdentity, incompatibleVectors, unconfirmedRename }

/// In-memory Core model. Persist with JSONEncoder at the caller's chosen local path.
public struct IdentityLibrary: Codable, Equatable, Sendable {
    public private(set) var enrollments: [IdentityEnrollment] = []
    public init() {}

    public static func load(from url: URL) throws -> IdentityLibrary {
        try JSONDecoder().decode(IdentityLibrary.self, from: Data(contentsOf: url))
    }
    public func save(to url: URL) throws {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try AtomicFile.write(try encoder.encode(self), to: url)
    }

    @discardableResult public mutating func add(_ enrollment: IdentityEnrollment) -> UUID {
        let pending = Self.pending(enrollment, splitFrom: nil)
        enrollments.append(pending)
        return pending.id
    }
    public mutating func confirm(_ id: UUID, name: String) throws {
        guard let i = enrollments.firstIndex(where: { $0.id == id }), !name.isEmpty else { throw IdentityLibraryError.missingIdentity }
        enrollments[i].displayName = name; enrollments[i].confirmed = true
        enrollments[i].history.append(.init(action: .confirmed, detail: name))
    }
    public mutating func rename(_ id: UUID, to name: String) throws {
        guard let i = enrollments.firstIndex(where: { $0.id == id }), !name.isEmpty else { throw IdentityLibraryError.missingIdentity }
        // Only explicitly confirmed identities may be renamed.
        guard enrollments[i].confirmed else { throw IdentityLibraryError.unconfirmedRename }
        enrollments[i].displayName = name; enrollments[i].history.append(.init(action: .renamed, detail: name))
    }
    @discardableResult public mutating func split(_ id: UUID, into newEnrollment: IdentityEnrollment) throws -> UUID {
        guard let i = enrollments.firstIndex(where: { $0.id == id }) else { throw IdentityLibraryError.missingIdentity }
        enrollments[i].history.append(.init(action: .split, detail: newEnrollment.id.uuidString))
        enrollments.append(Self.pending(newEnrollment, splitFrom: id))
        return newEnrollment.id
    }

    /// Removes caller-supplied identity claims from every newly added or split enrollment.
    private static func pending(_ enrollment: IdentityEnrollment, splitFrom parentID: UUID?) -> IdentityEnrollment {
        var pending = enrollment
        pending.displayName = nil
        pending.confirmed = false
        // A prefilled enrollment may carry forged confirmation/rename history as well.
        pending.history.removeAll { $0.action == .confirmed || $0.action == .renamed }
        if let parentID {
            pending.history.append(.init(action: .split, detail: "split from \(parentID.uuidString)"))
        }
        return pending
    }
    public mutating func merge(_ sourceID: UUID, into targetID: UUID) throws {
        guard sourceID != targetID,
              let s = enrollments.firstIndex(where: { $0.id == sourceID }),
              let t = enrollments.firstIndex(where: { $0.id == targetID }) else { throw IdentityLibraryError.missingIdentity }
        guard enrollments[s].embedding.count == enrollments[t].embedding.count else { throw IdentityLibraryError.incompatibleVectors }
        enrollments[t].samples.append(contentsOf: enrollments[s].samples)
        enrollments[t].history.append(.init(action: .merged, detail: sourceID.uuidString))
        enrollments[s].revoked = true; enrollments[s].history.append(.init(action: .merged, detail: "merged into \(targetID.uuidString)"))
    }
    public mutating func revoke(_ id: UUID, reason: String) throws {
        guard let i = enrollments.firstIndex(where: { $0.id == id }) else { throw IdentityLibraryError.missingIdentity }
        enrollments[i].revoked = true; enrollments[i].confirmed = false
        enrollments[i].history.append(.init(action: .revoked, detail: reason))
    }
    public func match(vector: [Float], minimumRawSimilarity: Double) -> IdentityMatch {
        let candidates = enrollments.filter { $0.confirmed && !$0.revoked && $0.embedding.count == vector.count && !vector.isEmpty }
        let scored = candidates.compactMap { enrollment -> (IdentityEnrollment, Double)? in
            let a = zip(vector, enrollment.embedding).reduce(0.0) { $0 + Double($1.0 * $1.1) }
            let na = sqrt(vector.reduce(0.0) { $0 + Double($1 * $1) })
            let nb = sqrt(enrollment.embedding.reduce(0.0) { $0 + Double($1 * $1) })
            guard na > 0, nb > 0 else { return nil }
            return (enrollment, a / (na * nb))
        }.sorted { $0.1 > $1.1 }
        guard let best = scored.first, best.1 >= minimumRawSimilarity else { return .unknown(bestScore: scored.first?.1) }
        return IdentityMatch(identityID: best.0.id, displayName: best.0.displayName,
                             rawSimilarityScore: best.1, scoreMeaning: "raw_similarity_not_probability")
    }
}
