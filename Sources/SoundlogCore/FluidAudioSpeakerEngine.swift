#if os(macOS) && canImport(FluidAudio)
import Foundation
import FluidAudio

public struct SpeakerModelInstallReceipt: Codable, Equatable, Sendable {
    public let modelRevision: String
    public let cacheDirectory: String
    public let verifiedAssetCount: Int
    public let verifiedBytes: Int
    public let attributionFiles: [String]
}

private struct FluidAudioModelManifest: Decodable, Sendable {
    struct Asset: Decodable, Sendable {
        let path: String
        let size: Int
        let sha256: String
    }

    let fluidAudioVersion: String
    let repository: String
    let revision: String
    let totalBytes: Int
    let assets: [Asset]
    let attributionFiles: [Asset]
}

/// Offline VBx speaker diarization backed by the pinned FluidAudio release.
public struct FluidAudioSpeakerEngine: SpeakerDiarizationEngine {
    public let identifier = "FluidAudio.OfflineVBx@0.17.7"
    private let config: OfflineDiarizerConfig

    public init(config: OfflineDiarizerConfig = .default) {
        self.config = config
    }

    /// Explicitly downloads the pinned offline model set, verifies every asset,
    /// preserves its attribution files, and loads the models without audio input.
    /// This is the only project API that enables model downloads.
    public static func installAndValidateModels() async throws -> SpeakerModelInstallReceipt {
        let manifest = try loadManifest()
        let modelsDirectory = OfflineDiarizerModels.defaultModelsDirectory()

        ModelHub.offlineMode = false
        try await ModelHub.download(.diarizer, to: modelsDirectory, variant: "offline")
        ModelHub.offlineMode = true

        let repoDirectory = modelsDirectory.appendingPathComponent(Repo.diarizer.folderName, isDirectory: true)
        try await preserveAttributionFiles(manifest.attributionFiles, repoDirectory: repoDirectory, manifest: manifest)
        let receipt = try verifyInstalledAssets(manifest, repoDirectory: repoDirectory)

        // Keep subsequent FluidAudio model loads in this process local-only.
        let models = try await OfflineDiarizerModels.load(from: modelsDirectory)
        let manager = OfflineDiarizerManager(config: .default)
        manager.initialize(models: models)

        return SpeakerModelInstallReceipt(
            modelRevision: receipt.modelRevision,
            cacheDirectory: receipt.cacheDirectory,
            verifiedAssetCount: receipt.verifiedAssetCount,
            verifiedBytes: receipt.verifiedBytes,
            attributionFiles: receipt.attributionFiles
        )
    }

    public func diarize(file: URL) async throws -> SpeakerEngineResult {
        let manifest = try Self.loadManifest()
        let modelsDirectory = OfflineDiarizerModels.defaultModelsDirectory()
        let repoDirectory = modelsDirectory.appendingPathComponent(Repo.diarizer.folderName, isDirectory: true)
        _ = try Self.verifyInstalledAssets(manifest, repoDirectory: repoDirectory)

        // FluidAudio's general-purpose prepareModels() can download on failure.
        // Loading with offlineMode enabled makes a missing or corrupt cache fail closed.
        ModelHub.offlineMode = true
        let models = try await OfflineDiarizerModels.load(from: modelsDirectory)
        let manager = OfflineDiarizerManager(config: config)
        manager.initialize(models: models)
        let result = try await manager.process(file)
        return SpeakerEngineResult(segments: result.segments.map {
            SpeakerSegment(
                speakerID: $0.speakerId,
                startOffsetSeconds: Double($0.startTimeSeconds),
                endOffsetSeconds: Double($0.endTimeSeconds)
            )
        })
    }

    private static func loadManifest() throws -> FluidAudioModelManifest {
        guard let url = Bundle.module.url(
            forResource: "speaker-diarization-coreml-v0.17.7",
            withExtension: "json"
        ) else {
            throw TranscriptionError.io("找不到内置 FluidAudio 模型清单")
        }
        let manifest = try JSONDecoder().decode(FluidAudioModelManifest.self, from: Data(contentsOf: url))
        guard manifest.fluidAudioVersion == "0.17.7",
              manifest.repository == "FluidInference/speaker-diarization-coreml",
              manifest.revision == "df2625ac79a7ac6b65ad868fee6d80f320da4232",
              manifest.assets.count == 21,
              manifest.assets.reduce(0, { $0 + $1.size }) == manifest.totalBytes else {
            throw TranscriptionError.io("FluidAudio 模型清单与已核验固定版本不一致")
        }
        return manifest
    }

    private static func verifyInstalledAssets(
        _ manifest: FluidAudioModelManifest,
        repoDirectory: URL
    ) throws -> SpeakerModelInstallReceipt {
        let fileManager = FileManager.default
        var actualBytes = 0
        for asset in manifest.assets {
            let file = repoDirectory.appendingPathComponent(asset.path)
            let data = try Data(contentsOf: file, options: [.mappedIfSafe])
            guard data.count == asset.size, SHA256.digest(data) == asset.sha256 else {
                throw TranscriptionError.io("FluidAudio 模型文件校验失败: \(asset.path)")
            }
            actualBytes += data.count
        }
        guard fileManager.fileExists(atPath: repoDirectory.path) else {
            throw TranscriptionError.io("FluidAudio 模型缓存目录不存在: \(repoDirectory.path)")
        }
        return SpeakerModelInstallReceipt(
            modelRevision: manifest.revision,
            cacheDirectory: repoDirectory.path,
            verifiedAssetCount: manifest.assets.count,
            verifiedBytes: actualBytes,
            attributionFiles: manifest.attributionFiles.map(\.path)
        )
    }

    private static func preserveAttributionFiles(
        _ files: [FluidAudioModelManifest.Asset],
        repoDirectory: URL,
        manifest: FluidAudioModelManifest
    ) async throws {
        try FileManager.default.createDirectory(at: repoDirectory, withIntermediateDirectories: true)
        for file in files {
            let destination = repoDirectory.appendingPathComponent(file.path)
            if FileManager.default.fileExists(atPath: destination.path) {
                let existing = try Data(contentsOf: destination, options: [.mappedIfSafe])
                if existing.count == file.size, SHA256.digest(existing) == file.sha256 { continue }
            }
            let source = "https://huggingface.co/\(manifest.repository)/resolve/\(manifest.revision)/\(file.path)"
            guard let url = URL(string: source) else { throw TranscriptionError.io("无效的模型来源地址") }
            var request = URLRequest(url: url)
            request.setValue("soundlog/FluidAudio-0.17.7", forHTTPHeaderField: "User-Agent")
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
                  data.count == file.size, SHA256.digest(data) == file.sha256 else {
                throw TranscriptionError.io("FluidAudio 许可或来源文件校验失败: \(file.path)")
            }
            try AtomicFile.write(data, to: destination)
        }
    }
}
#endif
