import Foundation
#if canImport(Glibc)
import Glibc
#elseif canImport(Darwin)
import Darwin
#endif

public struct IntegratedModuleStatus: Codable, Equatable, Sendable {
    public var state: String
    public var error: String?
    public var fingerprint: ResumeFingerprint?
    public var wallClockSeconds: Double?
    public var execution: String?
    public init(state: String, error: String? = nil, fingerprint: ResumeFingerprint? = nil, wallClockSeconds: Double? = nil, execution: String? = nil) {
        self.state = state; self.error = error; self.fingerprint = fingerprint; self.wallClockSeconds = wallClockSeconds; self.execution = execution
    }
}

public struct IntegratedProcessingStatus: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public let sourcePath: String
    public let sourceSHA256: String
    public var updatedAt: String
    public var modules: [String: IntegratedModuleStatus]
    public var runWallClockSecondsIncludingManifestWrite: Double?
    public init(sourcePath: String, sourceSHA256: String, updatedAt: String = ISO8601DateFormatter().string(from: Date()), modules: [String: IntegratedModuleStatus] = [:]) {
        schemaVersion = 1; self.sourcePath = sourcePath; self.sourceSHA256 = sourceSHA256; self.updatedAt = updatedAt; self.modules = modules; self.runWallClockSecondsIncludingManifestWrite = nil
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

/// Shared module boundary used by process and synthetic failure tests. A failed
/// module is persisted without preventing its caller from running later modules.
public enum IntegratedModuleExecutor {
    public static func skip(module: String, state: String = "skipped", reason: String, fingerprint: ResumeFingerprint? = nil, status: inout IntegratedProcessingStatus, statusURL: URL, encoder: JSONEncoder = JSONEncoder()) {
        status.record(module, state: state, error: reason, fingerprint: fingerprint)
        status.modules[module]?.execution = "skip"
        status.modules[module]?.wallClockSeconds = 0
        try? AtomicFile.write(try encoder.encode(status), to: statusURL)
    }
    @discardableResult
    public static func execute(module: String, fingerprint: ResumeFingerprint, artifactURL: URL? = nil, status: inout IntegratedProcessingStatus, statusURL: URL, encoder: JSONEncoder = JSONEncoder(), operation: @Sendable () async throws -> Void) async -> Bool {
        if let artifactURL, IntegratedModuleResumePlanner.plan(expected: fingerprint, status: status.modules[module], artifactURL: artifactURL) == .reuse {
            status.modules[module]?.execution = "reuse"
            status.modules[module]?.wallClockSeconds = 0
            try? AtomicFile.write(try encoder.encode(status), to: statusURL)
            return true
        }
        let started = Date()
        status.record(module, state: "running", fingerprint: fingerprint)
        do { try AtomicFile.write(try encoder.encode(status), to: statusURL) }
        catch {
            status.record(module, state: "failed", error: String(describing: error), fingerprint: fingerprint)
            try? AtomicFile.write(try encoder.encode(status), to: statusURL)
            return false
        }
        do {
            try await operation()
            let elapsed = Date().timeIntervalSince(started)
            status.record(module, state: "completed", fingerprint: fingerprint)
            status.modules[module]?.execution = "recomputed"
            status.modules[module]?.wallClockSeconds = elapsed
            try AtomicFile.write(try encoder.encode(status), to: statusURL)
            return true
        } catch {
            status.record(module, state: "failed", error: String(describing: error), fingerprint: fingerprint)
            status.modules[module]?.execution = "recomputed"
            status.modules[module]?.wallClockSeconds = Date().timeIntervalSince(started)
            try? AtomicFile.write(try encoder.encode(status), to: statusURL)
            return false
        }
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
    public let durationMethod: String
    public let durationError: String?
    public let performance: RunPerformance
    /// Audio coverage derived from transcription ranges only.
    public let coverage: CoverageReport?
    public let modules: [String: IntegratedModuleStatus]
    public let artifacts: [String: ArtifactRecord]
    public let samples: [String: ResultSamples]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, generatedAt, inputPath, sourceSHA256, audioDurationSeconds, durationMethod, durationError, performance, coverage, modules, artifacts, samples
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(generatedAt, forKey: .generatedAt)
        try container.encode(inputPath, forKey: .inputPath)
        try container.encode(sourceSHA256, forKey: .sourceSHA256)
        if let audioDurationSeconds { try container.encode(audioDurationSeconds, forKey: .audioDurationSeconds) }
        else { try container.encodeNil(forKey: .audioDurationSeconds) }
        try container.encode(durationMethod, forKey: .durationMethod)
        if let durationError { try container.encode(durationError, forKey: .durationError) }
        else { try container.encodeNil(forKey: .durationError) }
        try container.encode(performance, forKey: .performance)
        if let coverage { try container.encode(coverage, forKey: .coverage) }
        else { try container.encodeNil(forKey: .coverage) }
        try container.encode(modules, forKey: .modules)
        try container.encode(artifacts, forKey: .artifacts)
        try container.encode(samples, forKey: .samples)
    }
}

public struct RunPerformance: Codable, Equatable, Sendable {
    public let wallClockSeconds: Double
    public let peakMemoryBytes: UInt64
    public let peakMemorySource: String
    public let ruMaxRSSUnit: String
    public let wallClockExcludesManifestWrite: Bool
    public init(wallClockSeconds: Double, peakMemoryBytes: UInt64, peakMemorySource: String, ruMaxRSSUnit: String, wallClockExcludesManifestWrite: Bool = false) {
        self.wallClockSeconds = wallClockSeconds; self.peakMemoryBytes = peakMemoryBytes; self.peakMemorySource = peakMemorySource; self.ruMaxRSSUnit = ruMaxRSSUnit; self.wallClockExcludesManifestWrite = wallClockExcludesManifestWrite
    }
}

public enum ProcessPeakMemory {
    public static func current() -> (bytes: UInt64, source: String, unit: String) {
        #if canImport(Glibc) || canImport(Darwin)
        var usage = rusage()
        #if canImport(Glibc)
        guard getrusage(RUSAGE_SELF.rawValue, &usage) == 0 else { return (0, "getrusage-failed", "bytes") }
        return (UInt64(max(0, usage.ru_maxrss)) * 1024, "getrusage", "KB")
        #else
        guard getrusage(RUSAGE_SELF, &usage) == 0 else { return (0, "getrusage-failed", "bytes") }
        return (UInt64(max(0, usage.ru_maxrss)), "getrusage", "bytes")
        #endif
        #else
        return (0, "unavailable", "bytes")
        #endif
    }
}

public struct AudioDuration: Equatable, Sendable {
    public let seconds: Double?
    public let method: String
    public let error: String?
    public init(seconds: Double?, method: String, error: String?) { self.seconds = seconds; self.method = method; self.error = error }
}

public struct ArtifactRecord: Codable, Equatable, Sendable {
    public let path: String
    public let sha256: String
}

public enum UnifiedOutput {
    /// Parse container metadata without decoding audio. A failed parse never guesses.
    public static func audioDuration(file url: URL) throws -> AudioDuration {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let length = try handle.seekToEnd()
        func read(_ offset: UInt64, _ count: Int) throws -> Data {
            try handle.seek(toOffset: offset)
            return try handle.read(upToCount: count) ?? Data()
        }
        let head = try read(0, 12)
        if head.count >= 12, String(data: head[0..<4], encoding: .ascii) == "RIFF", String(data: head[8..<12], encoding: .ascii) == "WAVE",
           let duration = try wavDuration(fileLength: length, read: read) { return AudioDuration(seconds: duration, method: "wav-data-size", error: nil) }
        if let mp3 = try mp3Duration(fileLength: length, read: read) { return AudioDuration(seconds: mp3.seconds, method: mp3.method, error: nil) }
        if let mp4 = try mp4Duration(fileLength: length, read: read) { return AudioDuration(seconds: mp4, method: "mvhd/mdhd", error: nil) }
        if head.prefix(3).elementsEqual(Data("ID3".utf8)) || head.count >= 2 && head[0] == 0xff && head[1] & 0xe0 == 0xe0 { return AudioDuration(seconds: nil, method: "failed", error: "MP3帧头或时长元数据无效/截断") }
        if head.count >= 8, String(data: head[4..<8], encoding: .ascii) == "ftyp" { return AudioDuration(seconds: nil, method: "failed", error: "M4A中未找到有效mvhd/mdhd时长") }
        return AudioDuration(seconds: nil, method: "unsupported", error: "不支持的音频容器或无法识别的内容")
    }

    private static func wavDuration(fileLength: UInt64, read: (UInt64, Int) throws -> Data) throws -> Double? {
        var offset: UInt64 = 12, byteRate: UInt32?
        while offset + 8 <= fileLength {
            let h = try read(offset, 8); guard h.count == 8 else { return nil }
            let id = String(data: h.prefix(4), encoding: .ascii) ?? ""
            let size = UInt64(h[4..<8].enumerated().reduce(UInt32(0)) { $0 | UInt32($1.element) << (8 * $1.offset) })
            guard size <= fileLength - offset - 8 else { return nil }
            if id == "fmt ", size >= 16 {
                let fmt = try read(offset + 8, 16); if fmt.count == 16 { byteRate = fmt[8..<12].enumerated().reduce(UInt32(0)) { $0 | UInt32($1.element) << (8 * $1.offset) } }
            }
            if id == "data", let byteRate, byteRate > 0 { return Double(size) / Double(byteRate) }
            offset += 8 + size + (size % 2)
        }
        return nil
    }

    private static func mp3Duration(fileLength: UInt64, read: (UInt64, Int) throws -> Data) throws -> (seconds: Double, method: String)? {
        var offset: UInt64 = 0
        let first = try read(0, 10)
        if first.count == 10, first.prefix(3).elementsEqual(Data("ID3".utf8)) {
            guard first[6] < 128, first[7] < 128, first[8] < 128, first[9] < 128 else { return nil }
            offset = 10 + (UInt64(first[6]) << 21 | UInt64(first[7]) << 14 | UInt64(first[8]) << 7 | UInt64(first[9]))
            if first[5] & 0x10 != 0 { offset += 10 }
            guard offset <= fileLength else { return nil }
        }
        let bitrates: [[Int]] = [[], [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320], [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160]], rates = [44100,48000,32000]
        var frames = 0, total = 0.0
        while offset + 4 <= fileLength {
            let b = try read(offset, 4); guard b.count == 4 else { break }
            let h = UInt32(b[0]) << 24 | UInt32(b[1]) << 16 | UInt32(b[2]) << 8 | UInt32(b[3])
            guard h & 0xffe00000 == 0xffe00000 else { if frames == 0 { offset += 1; continue }; break }
            let version = Int((h >> 19) & 3), layer = Int((h >> 17) & 3), bi = Int((h >> 12) & 15), ri = Int((h >> 10) & 3)
            guard version != 1, layer == 1, bi > 0, bi < 15, ri < 3 else { if frames == 0 { offset += 1; continue }; break }
            let rate = rates[ri] / (version == 3 ? 1 : version == 2 ? 2 : 4), bitrate = bitrates[version == 3 ? 1 : 2][bi] * 1000
            let frameLength = (version == 3 ? 144 : 72) * bitrate / rate + Int((h >> 9) & 1)
            guard frameLength >= 24, UInt64(frameLength) <= fileLength - offset else { break }
            if frames == 0 {
                let mono = (h >> 6) & 3 == 3, side = version == 3 ? (mono ? 17 : 32) : (mono ? 9 : 17)
                let xoff = offset + UInt64(4 + (h & 0x10000 == 0 ? 2 : 0) + side)
                let x = try read(xoff, 16)
                if x.count >= 12, x.prefix(4).elementsEqual(Data("Xing".utf8)) || x.count >= 12 && x.prefix(4).elementsEqual(Data("Info".utf8)) {
                    let flags = x[4..<8].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
                    let count = x[8..<12].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
                    if flags & 1 != 0, count > 0 { return (Double(count) * Double(version == 3 ? 1152 : 576) / Double(rate), "xing") }
                }
                let v = try read(offset + 36, 18)
                if v.count >= 18, v.prefix(4).elementsEqual(Data("VBRI".utf8)) {
                    let count = v[14..<18].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
                    if count > 0 { return (Double(count) * Double(version == 3 ? 1152 : 576) / Double(rate), "vbri") }
                }
            }
            frames += 1; total += Double(version == 3 ? 1152 : 576) / Double(rate); offset += UInt64(frameLength)
        }
        guard frames > 0 else { return nil }
        if fileLength - offset == 128, try read(offset, 3).elementsEqual(Data("TAG".utf8)) { return (total, "frame-scan (ID3v1 skipped)") }
        return (total, offset == fileLength ? "frame-scan" : "frame-scan (trailing garbage ignored)")
    }

    private static func mp4Duration(fileLength: UInt64, read: (UInt64, Int) throws -> Data) throws -> Double? {
        func scan(_ lower: UInt64, _ upper: UInt64, _ depth: Int) throws -> Double? {
            guard depth < 12 else { return nil }; var at = lower
            while at + 8 <= upper {
                let h = try read(at, 8); guard h.count == 8 else { return nil }
                let size32 = UInt64(h[0..<4].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }), type = String(data: h[4..<8], encoding: .ascii) ?? ""
                var header: UInt64 = 8, size = size32
                if size32 == 1 {
                    let ext = try read(at + 8, 8); guard ext.count == 8 else { return nil }
                    size = ext.reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }; header = 16
                    guard size <= UInt64(Int.max) else { return nil }
                } else if size32 == 0 { size = upper - at }
                guard size >= header, size <= upper - at else { return nil }
                if type == "mvhd" || type == "mdhd" {
                    let p = at + header, v = try read(p, 32); guard !v.isEmpty else { return nil }
                    let ver = v[0], so = ver == 1 ? 20 : 12, d = ver == 1 ? 24 : 16, need = d + (ver == 1 ? 8 : 4)
                    guard v.count >= need else { return nil }
                    let scale = v[so..<so+4].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }; guard scale > 0 else { return nil }
                    let duration: UInt64 = ver == 1 ? v[d..<d+8].reduce(UInt64(0)) { ($0 << 8) | UInt64($1) } : UInt64(v[d..<d+4].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) })
                    if duration > 0 { return Double(duration) / Double(scale) }
                }
                if ["moov", "trak", "mdia"].contains(type), let result = try scan(at + header, at + size, depth + 1) { return result }
                at += size
            }
            return nil
        }
        return try scan(0, fileLength, 0)
    }

    public static func audioDuration(data: Data) -> AudioDuration {
        if let wav = wavDuration(data: data) { return AudioDuration(seconds: wav, method: "wav-data-size", error: nil) }
        if let mp3 = mp3Duration(data: data) { return AudioDuration(seconds: mp3.seconds, method: mp3.method, error: nil) }
        if let mp4 = mp4Duration(data: data) { return AudioDuration(seconds: mp4, method: "mvhd/mdhd", error: nil) }
        let prefix = String(data: data.prefix(12), encoding: .ascii) ?? ""
        if prefix.hasPrefix("ID3") || looksLikeMP3(data) { return AudioDuration(seconds: nil, method: "failed", error: "MP3帧头或时长元数据无效/截断") }
        if data.count >= 8, String(data: data[4..<8], encoding: .ascii) == "ftyp" { return AudioDuration(seconds: nil, method: "failed", error: "M4A中未找到有效mvhd/mdhd时长") }
        return AudioDuration(seconds: nil, method: "unsupported", error: "不支持的音频容器或无法识别的内容")
    }

    private static func looksLikeMP3(_ data: Data) -> Bool {
        if data.count >= 2 { for i in 0..<(data.count - 1) where data[i] == 0xff && data[i + 1] & 0xe0 == 0xe0 { return true } }
        return false
    }

    private static func mp3Duration(data: Data) -> (seconds: Double, method: String)? {
        try? mp3Duration(fileLength: UInt64(data.count)) { offset, count in
            guard offset <= UInt64(data.count) else { return Data() }
            let start = Int(offset), end = min(data.count, start + count)
            return start < end ? Data(data[start..<end]) : Data()
        }
    }

    private static func be32(_ data: Data, _ i: Int) -> UInt32 { UInt32(data[i]) << 24 | UInt32(data[i+1]) << 16 | UInt32(data[i+2]) << 8 | UInt32(data[i+3]) }

    private static func mp4Duration(data: Data) -> Double? {
        try? mp4Duration(fileLength: UInt64(data.count)) { offset, count in
            guard offset <= UInt64(data.count) else { return Data() }
            let start = Int(offset), end = min(data.count, start + count)
            return start < end ? Data(data[start..<end]) : Data()
        }
    }
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
        let started = Date()
        do {
            try AtomicFile.write(Data(renderTranscript(document, format: format).utf8), to: url)
            status.record("unifiedTranscript", state: "completed", fingerprint: fingerprint)
            status.modules["unifiedTranscript"]?.execution = "recomputed"
            status.modules["unifiedTranscript"]?.wallClockSeconds = Date().timeIntervalSince(started)
            try AtomicFile.write(try encoder.encode(status), to: statusURL)
        } catch {
            status.record("unifiedTranscript", state: "failed", error: String(describing: error), fingerprint: fingerprint)
            status.modules["unifiedTranscript"]?.execution = "recomputed"
            status.modules["unifiedTranscript"]?.wallClockSeconds = Date().timeIntervalSince(started)
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

    public static func buildManifest(inputPath: String, sourceSHA256: String, duration: Double?, coverageRanges: [AudioTimeRange], modules: [String: IntegratedModuleStatus], samples: [String: [String]], artifactURLs: [String: URL], baseDirectory: URL, generatedAt: String = ISO8601DateFormatter().string(from: Date()), durationMethod: String = "unknown", durationError: String? = nil, performance: RunPerformance = RunPerformance(wallClockSeconds: 0, peakMemoryBytes: 0, peakMemorySource: "unavailable", ruMaxRSSUnit: "bytes")) throws -> RunManifest {
        var artifacts: [String: ArtifactRecord] = [:]
        var registeredPaths = Set<String>()
        let statusPath = baseDirectory.appendingPathComponent("processing-status.json").standardizedFileURL.path
        for (name, url) in artifactURLs.sorted(by: { $0.key < $1.key }) where FileManager.default.fileExists(atPath: url.path) {
            let canonicalPath = url.standardizedFileURL.path
            guard canonicalPath != statusPath, registeredPaths.insert(canonicalPath).inserted else { continue }
            let relative = String(url.path.dropFirst(baseDirectory.path.hasSuffix("/") ? baseDirectory.path.count : baseDirectory.path.count + 1))
            artifacts[name] = ArtifactRecord(path: relative, sha256: try SHA256.file(url))
        }
        return RunManifest(schemaVersion: 1, generatedAt: generatedAt, inputPath: inputPath, sourceSHA256: sourceSHA256, audioDurationSeconds: duration, durationMethod: durationMethod, durationError: durationError, performance: performance,
            coverage: try duration.map { try coverageReport(ranges: coverageRanges, duration: $0) }, modules: modules,
            artifacts: artifacts, samples: samples.mapValues { self.samples($0) })
    }

    /// Builds and durably writes the manifest. Mutable processing status is excluded from its artifact hashes.
    @discardableResult
    public static func writeManifest(inputPath: String, sourceSHA256: String, duration: Double?, coverageRanges: [AudioTimeRange], modules: [String: IntegratedModuleStatus], samples: [String: [String]], artifactURLs: [String: URL], baseDirectory: URL, to manifestURL: URL, encoder: JSONEncoder = JSONEncoder(), generatedAt: String = ISO8601DateFormatter().string(from: Date()), durationMethod: String = "unknown", durationError: String? = nil, performance: RunPerformance = RunPerformance(wallClockSeconds: 0, peakMemoryBytes: 0, peakMemorySource: "unavailable", ruMaxRSSUnit: "bytes")) throws -> RunManifest {
        let manifest = try buildManifest(inputPath: inputPath, sourceSHA256: sourceSHA256, duration: duration, coverageRanges: coverageRanges, modules: modules, samples: samples, artifactURLs: artifactURLs, baseDirectory: baseDirectory, generatedAt: generatedAt, durationMethod: durationMethod, durationError: durationError, performance: performance)
        try AtomicFile.write(try encoder.encode(manifest), to: manifestURL)
        return manifest
    }
}
