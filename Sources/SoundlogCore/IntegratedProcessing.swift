import Foundation

public struct IntegratedModuleStatus: Codable, Equatable, Sendable {
    public var state: String
    public var error: String?
    public var fingerprint: ResumeFingerprint?
    public init(state: String, error: String? = nil, fingerprint: ResumeFingerprint? = nil) {
        self.state = state; self.error = error; self.fingerprint = fingerprint
    }
}

public struct IntegratedProcessingStatus: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public let sourcePath: String
    public let sourceSHA256: String
    public var updatedAt: String
    public var modules: [String: IntegratedModuleStatus]
    public init(sourcePath: String, sourceSHA256: String, updatedAt: String = ISO8601DateFormatter().string(from: Date()), modules: [String: IntegratedModuleStatus] = [:]) {
        schemaVersion = 1; self.sourcePath = sourcePath; self.sourceSHA256 = sourceSHA256; self.updatedAt = updatedAt; self.modules = modules
    }
    public mutating func record(_ module: String, state: String, error: String? = nil, fingerprint: ResumeFingerprint? = nil) {
        modules[module] = IntegratedModuleStatus(state: state, error: error, fingerprint: fingerprint)
        updatedAt = ISO8601DateFormatter().string(from: Date())
    }
}

public enum IntegratedModuleResumePlanner {
    public static func plan(expected: ResumeFingerprint, status: IntegratedModuleStatus?, artifactURL: URL) -> ResumeDecision {
        guard let status else { return .rerun("无模块记录") }
        guard status.state == "completed" else { return .rerun("模块未完成") }
        guard status.fingerprint == expected else { return .rerun("哈希、参数或引擎指纹变") }
        guard let data = try? Data(contentsOf: artifactURL), !data.isEmpty,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let schemaVersion = object["schemaVersion"] as? Int, schemaVersion > 0,
              let sourceSHA256 = object["sourceSHA256"] as? String,
              sourceSHA256 == expected.sourceSHA256 else { return .rerun("产物缺失、无效或源哈希不符") }
        let reportedEngine = (object["engine"] as? String) ?? (object["alignmentMethod"] as? String)
        guard reportedEngine == expected.engine else { return .rerun("产物引擎指纹不符") }
        if let reportedParameters = object["parameters"] as? [String: Any] {
            for (key, expectedValue) in expected.parameters {
                guard let value = reportedParameters[key] else { return .rerun("产物参数缺失") }
                if let string = value as? String, string == expectedValue { continue }
                if let number = value as? NSNumber, let expectedNumber = Double(expectedValue), number.doubleValue == expectedNumber { continue }
                return .rerun("产物参数指纹不符")
            }
        }
        return .reuse
    }
}

public enum IntegratedArtifactValidator {
    public static func validate(range: AudioTimeRange) throws {
        _ = try AudioTimeRange(startOffsetSeconds: range.startOffsetSeconds, endOffsetSeconds: range.endOffsetSeconds)
    }
    public static func validate(coverage: [AudioTimeRange]) throws {
        guard !coverage.isEmpty else { throw TranscriptionError.invalidCoverage }
        for range in coverage { try validate(range: range) }
        try AudioTimeRange.validateChronological(coverage)
    }
    /// Failure/unsupported states remain explicit and JSON serializable, including model absence.
    public static func validate(status: IntegratedProcessingStatus) throws {
        let encoder = JSONEncoder()
        _ = try encoder.encode(status)
        for module in status.modules.values where module.state.isEmpty { throw TranscriptionError.io("空模块状态") }
    }
}

public struct CoverageReport: Codable, Equatable, Sendable {
    public let audioDurationSeconds: Double
    public let coveredSeconds: Double
    public let gaps: [AudioTimeRangeCodable]
}

public struct ResultSamples: Codable, Equatable, Sendable {
    public let first: [String]
    public let middle: [String]
    public let last: [String]
}

public struct RunManifest: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let generatedAt: String
    public let inputPath: String
    public let sourceSHA256: String
    public let audioDurationSeconds: Double?
    /// Audio coverage derived from transcription ranges only.
    public let coverage: CoverageReport?
    public let modules: [String: IntegratedModuleStatus]
    public let artifacts: [String: ArtifactRecord]
    public let samples: [String: ResultSamples]
}

public struct ArtifactRecord: Codable, Equatable, Sendable {
    public let path: String
    public let sha256: String
}

public enum UnifiedOutput {
    public static func candidateLabels(_ entry: SpeakerAlignedTranscriptEntry) -> [String] {
        var labels = entry.speakerCandidates.sorted()
        if entry.hasUnattributedOverlap { labels.append("未知") }
        return labels
    }

    public static func wavDuration(data: Data) -> Double? {
        guard data.count >= 44, String(data: data[0..<4], encoding: .ascii) == "RIFF", String(data: data[8..<12], encoding: .ascii) == "WAVE" else { return nil }
        func u32(_ offset: Int) -> UInt32 { data[offset..<offset + 4].enumerated().reduce(0) { $0 | UInt32($1.element) << (8 * $1.offset) } }
        var offset = 12, byteRate: UInt32?
        while offset + 8 <= data.count {
            let id = String(data: data[offset..<offset + 4], encoding: .ascii) ?? ""
            let size = Int(u32(offset + 4)); guard size >= 0, offset + 8 + size <= data.count else { return nil }
            if id == "fmt ", size >= 16 { byteRate = u32(offset + 16) }
            if id == "data", let byteRate, byteRate > 0 { return Double(size) / Double(byteRate) }
            offset += 8 + size + (size % 2)
        }
        return nil
    }

    /// Candidate labels remain anonymous IDs; identity names are deliberately not accepted.
    public static func renderTranscript(_ document: SpeakerAlignedTranscriptDocument, format: String) -> String {
        let lines = document.segments.map { entry -> String in
            let labels = candidateLabels(entry)
            let candidates = labels.isEmpty ? "未匹配" : labels.joined(separator: "、")
            return "- [\(entry.absoluteStartLocal)] [说话人候选：\(candidates)] \(entry.text)"
        }
        if format == "txt" { return lines.map { $0.replacingOccurrences(of: "- [", with: "[") }.joined(separator: "\n") + (lines.isEmpty ? "" : "\n") }
        return "# 逐字稿（说话人均为时间重叠候选，未经身份确认）\n\n" + lines.joined(separator: "\n") + (lines.isEmpty ? "" : "\n")
    }

    /// Writes the unified transcript and persists its outcome in processing status.
    public static func writeTranscript(_ document: SpeakerAlignedTranscriptDocument, format: String, to url: URL, status: inout IntegratedProcessingStatus, statusURL: URL, fingerprint: ResumeFingerprint, encoder: JSONEncoder = JSONEncoder()) throws {
        do {
            try AtomicFile.write(Data(renderTranscript(document, format: format).utf8), to: url)
            status.record("unifiedTranscript", state: "completed", fingerprint: fingerprint)
            try AtomicFile.write(try encoder.encode(status), to: statusURL)
        } catch {
            status.record("unifiedTranscript", state: "failed", error: String(describing: error), fingerprint: fingerprint)
            try? AtomicFile.write(try encoder.encode(status), to: statusURL)
            throw error
        }
    }

    public static func coverageReport(ranges: [AudioTimeRange], duration: Double) throws -> CoverageReport {
        guard duration.isFinite, duration >= 0 else { throw TranscriptionError.invalidCoverage }
        for range in ranges { _ = try AudioTimeRange(startOffsetSeconds: range.startOffsetSeconds, endOffsetSeconds: range.endOffsetSeconds, durationSeconds: duration) }
        let sorted = ranges.sorted { $0.startOffsetSeconds < $1.startOffsetSeconds }
        var gaps: [AudioTimeRangeCodable] = [], cursor = 0.0, covered = 0.0
        for range in sorted {
            if range.startOffsetSeconds > cursor { gaps.append(AudioTimeRangeCodable(try AudioTimeRange(startOffsetSeconds: cursor, endOffsetSeconds: range.startOffsetSeconds))) }
            let start = max(cursor, range.startOffsetSeconds)
            if range.endOffsetSeconds > start { covered += range.endOffsetSeconds - start }
            cursor = max(cursor, range.endOffsetSeconds)
        }
        if cursor < duration { gaps.append(AudioTimeRangeCodable(try AudioTimeRange(startOffsetSeconds: cursor, endOffsetSeconds: duration))) }
        return CoverageReport(audioDurationSeconds: duration, coveredSeconds: covered, gaps: gaps)
    }

    public static func samples(_ entries: [String], count: Int = 3) -> ResultSamples {
        guard !entries.isEmpty else { return ResultSamples(first: [], middle: [], last: []) }
        let n = min(count, entries.count), start = Array(entries.prefix(n)), end = Array(entries.suffix(n))
        let middleStart = max(0, (entries.count - n) / 2)
        return ResultSamples(first: start, middle: Array(entries[middleStart..<(middleStart + n)]), last: end)
    }

    public static func buildManifest(inputPath: String, sourceSHA256: String, duration: Double?, coverageRanges: [AudioTimeRange], modules: [String: IntegratedModuleStatus], samples: [String: [String]], artifactURLs: [String: URL], baseDirectory: URL, generatedAt: String = ISO8601DateFormatter().string(from: Date())) throws -> RunManifest {
        var artifacts: [String: ArtifactRecord] = [:]
        var registeredPaths = Set<String>()
        let statusPath = baseDirectory.appendingPathComponent("processing-status.json").standardizedFileURL.path
        for (name, url) in artifactURLs.sorted(by: { $0.key < $1.key }) where FileManager.default.fileExists(atPath: url.path) {
            let canonicalPath = url.standardizedFileURL.path
            guard canonicalPath != statusPath, registeredPaths.insert(canonicalPath).inserted else { continue }
            let relative = String(url.path.dropFirst(baseDirectory.path.hasSuffix("/") ? baseDirectory.path.count : baseDirectory.path.count + 1))
            artifacts[name] = ArtifactRecord(path: relative, sha256: try SHA256.file(url))
        }
        return RunManifest(schemaVersion: 1, generatedAt: generatedAt, inputPath: inputPath, sourceSHA256: sourceSHA256, audioDurationSeconds: duration,
            coverage: try duration.map { try coverageReport(ranges: coverageRanges, duration: $0) }, modules: modules,
            artifacts: artifacts, samples: samples.mapValues { self.samples($0) })
    }

    /// Builds and durably writes the manifest. Mutable processing status is excluded from its artifact hashes.
    @discardableResult
    public static func writeManifest(inputPath: String, sourceSHA256: String, duration: Double?, coverageRanges: [AudioTimeRange], modules: [String: IntegratedModuleStatus], samples: [String: [String]], artifactURLs: [String: URL], baseDirectory: URL, to manifestURL: URL, encoder: JSONEncoder = JSONEncoder(), generatedAt: String = ISO8601DateFormatter().string(from: Date())) throws -> RunManifest {
        let manifest = try buildManifest(inputPath: inputPath, sourceSHA256: sourceSHA256, duration: duration, coverageRanges: coverageRanges, modules: modules, samples: samples, artifactURLs: artifactURLs, baseDirectory: baseDirectory, generatedAt: generatedAt)
        try AtomicFile.write(try encoder.encode(manifest), to: manifestURL)
        return manifest
    }
}
