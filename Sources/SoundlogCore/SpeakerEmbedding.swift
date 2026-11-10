import Foundation

/// Represents the extracted speaker embedding vector for an anonymous speaker.
public struct SpeakerEmbedding: Codable, Equatable, Sendable {
    public let speakerID: String
    public let embedding: [Float]
    public let modelVersion: String
    public let engineVersion: String

    public init(speakerID: String, embedding: [Float], modelVersion: String, engineVersion: String) {
        self.speakerID = speakerID
        self.embedding = embedding
        self.modelVersion = modelVersion
        self.engineVersion = engineVersion
    }
}

/// Protocol for speaker embedding extraction.
/// Given an audio file and anonymous speaker timeline entries, produces embedding vectors for each speaker.
public protocol SpeakerEmbeddingExtractor: Sendable {
    var identifier: String { get }
    var modelVersion: String { get }
    var engineVersion: String { get }
    func extractEmbeddings(file: URL, segments: [SpeakerTimelineEntry]) async throws -> [SpeakerEmbedding]
}

extension SpeakerEmbeddingExtractor {
    public func extractEmbeddings(file: URL, timeline: SpeakerTimelineDocument) async throws -> [SpeakerEmbedding] {
        try await extractEmbeddings(file: file, segments: timeline.segments)
    }
}

/// Linux/mock speaker embedding extractor.
/// Generates deterministic fake vectors based on audio file hash and speaker identifier.
/// Identifier contains "mock".
public struct MockSpeakerEmbeddingExtractor: SpeakerEmbeddingExtractor {
    public let identifier: String
    public let modelVersion: String
    public let engineVersion: String
    public let dimension: Int

    public init(
        identifier: String = "FluidAudio.Embedding-mock@0.17.7",
        modelVersion: String = "mock-embedding-v1",
        engineVersion: String = "mock-engine-v1",
        dimension: Int = 256
    ) {
        self.identifier = identifier
        self.modelVersion = modelVersion
        self.engineVersion = engineVersion
        self.dimension = dimension
    }

    public func extractEmbeddings(file: URL, segments: [SpeakerTimelineEntry]) async throws -> [SpeakerEmbedding] {
        let durationInfo = try UnifiedOutput.audioDuration(file: file)
        guard let duration = durationInfo.seconds, duration > 0 else {
            throw TranscriptionError.io("Mock 声纹提取引擎校验失败: 无法解析音频有效时长 (\(durationInfo.error ?? "无效或损坏的音频"))")
        }

        let fileHash = try SHA256.file(file)

        // Find unique non-nil speaker IDs preserving order of appearance
        var seen = Set<String>()
        var speakerIDs: [String] = []
        for segment in segments {
            if let spk = segment.speakerID, !spk.isEmpty, seen.insert(spk).inserted {
                speakerIDs.append(spk)
            }
        }
        if speakerIDs.isEmpty {
            speakerIDs = ["SPEAKER_00"]
        }

        var results: [SpeakerEmbedding] = []
        for spk in speakerIDs {
            let vector = Self.generateDeterministicVector(fileHash: fileHash, speakerID: spk, dimension: dimension)
            results.append(SpeakerEmbedding(
                speakerID: spk,
                embedding: vector,
                modelVersion: modelVersion,
                engineVersion: engineVersion
            ))
        }
        return results
    }

    /// Generates a deterministic unit vector from file hash and speaker ID.
    public static func generateDeterministicVector(fileHash: String, speakerID: String, dimension: Int = 256) -> [Float] {
        let seedString = "\(fileHash):\(speakerID)"
        let digest = SHA256.digest(Data(seedString.utf8))
        var state: UInt64 = 0
        for byte in digest.utf8 {
            state = state &* 31 &+ UInt64(byte)
        }
        var vector: [Float] = []
        for _ in 0..<dimension {
            state = state &* 6364136223846793005 &+ 1442695040888963407
            let val = Float(Double(Int32(truncatingIfNeeded: state >> 32)) / Double(Int32.max))
            vector.append(val)
        }
        let norm = sqrt(vector.reduce(0.0) { $0 + Double($1 * $1) })
        if norm > 0 {
            return vector.map { Float(Double($0) / norm) }
        }
        return vector
    }
}

#if os(macOS) && canImport(FluidAudio)
import FluidAudio

/// Mac-only FluidAudio speaker embedding extractor.
///
/// 注意：本实现为 macOS 专用，未在 macOS 实体机验证。
/// 真实模型推理预留给 Mac 环境；未在 Mac 验证前抛出明确的待实现错误。
public struct FluidAudioSpeakerEmbeddingExtractor: SpeakerEmbeddingExtractor {
    public let identifier = "FluidAudio.Embedding@0.17.7"
    public let modelVersion = "FluidAudio-0.17.7-vbx"
    public let engineVersion = "FluidAudio-0.17.7"

    public init() {}

    public func extractEmbeddings(file: URL, segments: [SpeakerTimelineEntry]) async throws -> [SpeakerEmbedding] {
        // TODO: macOS 专用 - 待在 macOS 实体机结合 FluidAudio 0.17.7 离线模型验证声纹提取 API。
        // FluidAudio 内部 OfflineEmbeddingExtractor 需与离线模型加载配合，当前预留骨架。
        throw TranscriptionError.io("FluidAudio 声纹提取 Mac 待实现/待验证: 需在 macOS 实体机验证离线 embedding API")
    }
}
#endif

/// An identity assignment for an anonymous speaker in a recording.
public struct SpeakerIdentityAssignment: Codable, Equatable, Sendable {
    public let speakerID: String
    public let identityID: UUID?
    public let displayName: String?
    public let rawSimilarityScore: Double?
    public let scoreMeaning: String

    public init(
        speakerID: String,
        identityID: UUID?,
        displayName: String?,
        rawSimilarityScore: Double?,
        scoreMeaning: String = "raw_similarity_not_probability"
    ) {
        self.speakerID = speakerID
        self.identityID = identityID
        self.displayName = displayName
        self.rawSimilarityScore = rawSimilarityScore
        self.scoreMeaning = scoreMeaning
    }

    public init(speakerID: String, match: IdentityMatch) {
        self.speakerID = speakerID
        self.identityID = match.identityID
        self.displayName = match.displayName
        self.rawSimilarityScore = match.rawSimilarityScore
        self.scoreMeaning = match.scoreMeaning
    }
}

/// Document format for speaker-identities.json.
public struct SpeakerIdentitiesDocument: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let sourcePath: String
    public let sourceSHA256: String
    public let extractorEngine: String
    public let threshold: Double
    public let assignments: [SpeakerIdentityAssignment]

    public init(
        schemaVersion: Int = 1,
        sourcePath: String,
        sourceSHA256: String,
        extractorEngine: String,
        threshold: Double,
        assignments: [SpeakerIdentityAssignment]
    ) {
        self.schemaVersion = schemaVersion
        self.sourcePath = sourcePath
        self.sourceSHA256 = sourceSHA256
        self.extractorEngine = extractorEngine
        self.threshold = threshold
        self.assignments = assignments
    }
}

/// Pipeline that takes an audio file, speaker timeline, extracts embeddings,
/// compares against an IdentityLibrary (read-only), and writes speaker-identities.json.
public struct SpeakerIdentityPipeline: Sendable {
    public let extractor: any SpeakerEmbeddingExtractor
    public let identityLibrary: IdentityLibrary
    public let threshold: Double

    public init(
        extractor: any SpeakerEmbeddingExtractor,
        identityLibrary: IdentityLibrary,
        threshold: Double = 0.8
    ) {
        self.extractor = extractor
        self.identityLibrary = identityLibrary
        self.threshold = threshold
    }

    public func run(
        file: URL,
        timeline: SpeakerTimelineDocument,
        runDirectory: URL
    ) async throws -> SpeakerIdentitiesDocument {
        let embeddings = try await extractor.extractEmbeddings(file: file, segments: timeline.segments)
        var assignments: [SpeakerIdentityAssignment] = []
        for emb in embeddings {
            let match = try identityLibrary.match(vector: emb.embedding, minimumRawSimilarity: threshold)
            assignments.append(SpeakerIdentityAssignment(speakerID: emb.speakerID, match: match))
        }

        let document = SpeakerIdentitiesDocument(
            schemaVersion: 1,
            sourcePath: file.path,
            sourceSHA256: timeline.sourceSHA256,
            extractorEngine: extractor.identifier,
            threshold: threshold,
            assignments: assignments
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let destination = runDirectory.appendingPathComponent("speaker-identities.json")
        try AtomicFile.write(try encoder.encode(document), to: destination)
        return document
    }
}
