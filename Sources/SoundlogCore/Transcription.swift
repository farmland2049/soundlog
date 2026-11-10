import Foundation

public struct CLIOptions: Equatable, Sendable {
    public enum Command: String, Sendable { case manifest, transcribe, soundEvents = "sound-events", speakerDiarize = "speaker-diarize", process }
    public let command: Command
    public let input: URL
    public let outputRoot: URL
    public let engine: String
    public let parameters: [String: String]
    public let runDirectory: URL?

    public static func parse(_ arguments: [String]) throws -> CLIOptions {
        guard let first = arguments.first, let command = Command(rawValue: first) else { throw TranscriptionError.usage("用法: SoundlogCLI <manifest|transcribe|sound-events|speaker-diarize|process> --input 路径 --output-dir 路径 [--engine 标识] [--run-dir 已有运行目录] [--param key=value]；安装说话人模型: SoundlogCLI speaker-models install") }
        var values: [String: String] = [:], parameters: [String: String] = [:]
        var index = 1
        while index < arguments.count {
            let key = arguments[index]
            guard index + 1 < arguments.count else { throw TranscriptionError.usage("参数缺少值: \(key)") }
            let value = arguments[index + 1]
            if key == "--param" {
                let pair = value.split(separator: "=", maxSplits: 1).map(String.init)
                guard pair.count == 2, !pair[0].isEmpty else { throw TranscriptionError.usage("--param 需要 key=value") }
                parameters[pair[0]] = pair[1]
            } else if ["--input", "--output-dir", "--engine", "--run-dir"].contains(key), values[key] == nil { values[key] = value }
            else { throw TranscriptionError.usage("未知或重复参数: \(key)") }
            index += 2
        }
        guard let input = values["--input"], let output = values["--output-dir"] else { throw TranscriptionError.usage("必须提供 --input 和 --output-dir") }
        return CLIOptions(command: command, input: URL(fileURLWithPath: input), outputRoot: URL(fileURLWithPath: output), engine: values["--engine"] ?? "apple-speech-analyzer", parameters: parameters, runDirectory: values["--run-dir"].map { URL(fileURLWithPath: $0) })
    }
}

public enum TranscriptionError: Error, Equatable, Sendable {
    case usage(String), inputNotFound(String), invalidStartTime(String), unsupportedPlatform
    case invalidCoverage, emptyResult, io(String)
}

public enum SHA256 {
    private static let k: [UInt32] = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]
    private static func rotr(_ x: UInt32, _ n: UInt32) -> UInt32 { (x >> n) | (x << (32 - n)) }
    public struct Hasher {
        private var h: [UInt32] = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]
        private var pending: [UInt8] = []
        private var byteCount: UInt64 = 0
        private var finalized = false
        public init() {}
        public mutating func update(_ data: Data) {
            precondition(!finalized)
            byteCount &+= UInt64(data.count)
            pending.append(contentsOf: data)
            let complete = pending.count / 64 * 64
            if complete > 0 {
                for offset in stride(from: 0, to: complete, by: 64) { compress(Array(pending[offset..<offset + 64])) }
                pending.removeSubrange(0..<complete)
            }
        }
        private mutating func compress(_ bytes: [UInt8]) {
            var w = [UInt32](repeating: 0, count: 64)
            for i in 0..<16 { let p = i * 4; w[i] = UInt32(bytes[p]) << 24 | UInt32(bytes[p+1]) << 16 | UInt32(bytes[p+2]) << 8 | UInt32(bytes[p+3]) }
            for i in 16..<64 { let a = w[i-15], b = w[i-2]; w[i] = w[i-16] &+ (rotr(a,7) ^ rotr(a,18) ^ (a >> 3)) &+ w[i-7] &+ (rotr(b,17) ^ rotr(b,19) ^ (b >> 10)) }
            var (a,b,c,d,e,f,g,hh) = (h[0],h[1],h[2],h[3],h[4],h[5],h[6],h[7])
            for i in 0..<64 { let t1 = hh &+ (rotr(e,6) ^ rotr(e,11) ^ rotr(e,25)) &+ ((e & f) ^ (~e & g)) &+ k[i] &+ w[i]; let t2 = (rotr(a,2) ^ rotr(a,13) ^ rotr(a,22)) &+ ((a & b) ^ (a & c) ^ (b & c)); (hh,g,f,e,d,c,b,a) = (g,f,e,d &+ t1,c,b,a,t1 &+ t2) }
            for (i,v) in [a,b,c,d,e,f,g,hh].enumerated() { h[i] &+= v }
        }
        public mutating func finalize() -> String {
            precondition(!finalized); finalized = true
            var tail = pending
            tail.append(0x80); while tail.count % 64 != 56 { tail.append(0) }
            var bits = byteCount &* 8
            withUnsafeBytes(of: &bits) { tail.append(contentsOf: $0.reversed()) }
            for offset in stride(from: 0, to: tail.count, by: 64) { compress(Array(tail[offset..<offset+64])) }
            return h.map { String(format: "%08x", $0) }.joined()
        }
    }
    public static func digest(_ data: Data) -> String { var hasher = Hasher(); hasher.update(data); return hasher.finalize() }
    public static func file(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        var hasher = Hasher()
        while let chunk = try handle.read(upToCount: 1_048_576), !chunk.isEmpty { hasher.update(chunk) }
        return hasher.finalize()
    }
}

public struct SourceManifestEntry: Codable, Equatable, Sendable {
    public let path: String
    public let sha256: String
    public init(path: String, sha256: String) { self.path = path; self.sha256 = sha256 }
}
public enum InputEnumerator {
    public static let audioExtensions: Set<String> = ["wav","mp3","m4a","aac","aif","aiff","caf","flac","ogg","opus"]
    public static func files(at input: URL) throws -> [URL] {
        let fm = FileManager.default
        var isDir: ObjCBool = false
        guard fm.fileExists(atPath: input.path, isDirectory: &isDir) else { throw TranscriptionError.inputNotFound(input.path) }
        if !isDir.boolValue { return [input] }
        let urls = try fm.contentsOfDirectory(at: input, includingPropertiesForKeys: [.isRegularFileKey], options: [.skipsHiddenFiles])
        return urls.filter { audioExtensions.contains($0.pathExtension.lowercased()) }.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }
    public static func manifest(at input: URL) throws -> [SourceManifestEntry] { try files(at: input).map { SourceManifestEntry(path: $0.path, sha256: try SHA256.file($0)) } }
}

public struct ResumeFingerprint: Codable, Equatable, Sendable {
    public let sourceSHA256: String; public let engine: String; public let parameters: [String: String]
    public init(sourceSHA256: String, engine: String, parameters: [String: String]) { self.sourceSHA256 = sourceSHA256; self.engine = engine; self.parameters = parameters }
    public func mayReuse(_ previous: ResumeFingerprint?) -> Bool { previous == self }
}

public enum ResumeDecision: Equatable, Sendable { case reuse, rerun(String) }
public enum ResumePlanner {
    public static func plan(expected: ResumeFingerprint, statusURL: URL, rawURL: URL) -> ResumeDecision {
        guard FileManager.default.fileExists(atPath: statusURL.path),
              let data = try? Data(contentsOf: statusURL),
              let status = try? JSONDecoder().decode(TranscriptionStatus.self, from: data) else { return .rerun("无记录") }
        guard status.state != .failed else { return .rerun("上次失败") }
        guard status.fingerprint.sourceSHA256 == expected.sourceSHA256 else { return .rerun("哈希变") }
        guard status.fingerprint.engine == expected.engine else { return .rerun("引擎变") }
        guard status.fingerprint.parameters == expected.parameters else { return .rerun("参数变") }
        guard status.state == .completedWithText || status.state == .completedNoText,
              let rawData = try? Data(contentsOf: rawURL), !rawData.isEmpty,
              let raw = try? JSONDecoder().decode(RawTranscription.self, from: rawData),
              raw.schemaVersion > 0,
              raw.sourceSHA256 == expected.sourceSHA256,
              raw.engine == expected.engine,
              raw.parameters == expected.parameters else { return .rerun("产物缺失、无效或指纹不符") }
        return .reuse
    }
}
public enum TranscriptionState: String, Codable, Sendable { case completedWithText = "completed_with_text", completedNoText = "completed_no_text", failed }
public struct TranscriptionStatus: Codable, Equatable, Sendable {
    public let state: TranscriptionState; public let error: String?; public let fingerprint: ResumeFingerprint
    public init(state: TranscriptionState, error: String? = nil, fingerprint: ResumeFingerprint) { self.state = state; self.error = error; self.fingerprint = fingerprint }
}

public struct TranscriptSegment: Codable, Equatable, Sendable {
    public let startOffsetSeconds: Double; public let endOffsetSeconds: Double; public let text: String
    public init(start: Double, end: Double, text: String) { startOffsetSeconds = start; endOffsetSeconds = end; self.text = text }
}
public struct RawTranscription: Codable, Equatable, Sendable {
    public let schemaVersion: Int; public let sourcePath: String; public let sourceSHA256: String
    public let engine: String; public let parameters: [String: String]; public let recordingStartLocal: String
    public let segments: [TranscriptSegment]; public let coverage: [AudioTimeRangeCodable]; public let textRanges: [AudioTimeRangeCodable]; public let status: String; public let accuracyAssessment: String
}
public struct AudioTimeRangeCodable: Codable, Equatable, Sendable {
    public let start: Double; public let end: Double
    public init(_ range: AudioTimeRange) { start = range.startOffsetSeconds; end = range.endOffsetSeconds }
}
public struct EngineResult: Sendable { public let segments: [TranscriptSegment]; public let coveredRanges: [AudioTimeRange] }
public protocol TranscriptionEngine: Sendable { var identifier: String { get }; func transcribe(file: URL) async throws -> EngineResult }

public protocol AtomicFileWriting: Sendable { func write(_ data: Data, to destination: URL) throws }
public struct DefaultAtomicFileWriter: AtomicFileWriting {
    public init() {}
    public func write(_ data: Data, to destination: URL) throws { try AtomicFile.writeDefault(data, to: destination) }
}

public enum AtomicFile {
    public static func write(_ data: Data, to destination: URL, using writer: any AtomicFileWriting = DefaultAtomicFileWriter()) throws {
        try writer.write(data, to: destination)
    }
    fileprivate static func writeDefault(_ data: Data, to destination: URL) throws {
        let fm = FileManager.default; try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        let temporary = destination.deletingLastPathComponent().appendingPathComponent(".\(destination.lastPathComponent).\(UUID().uuidString).tmp")
        do { try data.write(to: temporary, options: .withoutOverwriting); if rename(temporary.path, destination.path) != 0 { throw TranscriptionError.io("无法原子替换 \(destination.path)") } }
        catch { try? fm.removeItem(at: temporary); throw error }
    }
    public static func writeStreaming(to destination: URL, _ body: (FileHandle) throws -> Void) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        let temporary = destination.deletingLastPathComponent().appendingPathComponent(".\(destination.lastPathComponent).\(UUID().uuidString).tmp")
        guard fm.createFile(atPath: temporary.path, contents: nil) else { throw TranscriptionError.io("无法创建临时文件 \(temporary.path)") }
        do {
            let handle = try FileHandle(forWritingTo: temporary)
            do { try body(handle); try handle.synchronize(); try handle.close() }
            catch { try? handle.close(); throw error }
            if rename(temporary.path, destination.path) != 0 { throw TranscriptionError.io("无法原子替换 \(destination.path)，errno \(errno)") }
        } catch { try? fm.removeItem(at: temporary); throw error }
    }
}

public struct TranscriptionPipeline: Sendable {
    public let engine: any TranscriptionEngine
    public init(engine: any TranscriptionEngine) { self.engine = engine }
    public func run(file: URL, runDirectory: URL, parameters: [String: String] = [:]) async throws -> RawTranscription {
        let start: RecordingStart
        do { start = try RecordingStart(filename: file.lastPathComponent) } catch { throw TranscriptionError.invalidStartTime(file.lastPathComponent) }
        let hash = try SHA256.file(file), result = try await engine.transcribe(file: file)
        guard !result.coveredRanges.isEmpty else { throw TranscriptionError.invalidCoverage }
        try AudioTimeRange.validateChronological(result.coveredRanges)
        for range in result.coveredRanges { _ = try AudioTimeRange(startOffsetSeconds: range.startOffsetSeconds, endOffsetSeconds: range.endOffsetSeconds) }
        let covered = result.coveredRanges.sorted { $0.startOffsetSeconds < $1.startOffsetSeconds }
        for segment in result.segments {
            let segmentRange = try AudioTimeRange(startOffsetSeconds: segment.startOffsetSeconds, endOffsetSeconds: segment.endOffsetSeconds)
            guard covered.contains(where: { $0.startOffsetSeconds <= segmentRange.startOffsetSeconds && $0.endOffsetSeconds >= segmentRange.endOffsetSeconds }) else { throw TranscriptionError.invalidCoverage }
        }
        let hasWords = result.segments.contains { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let textRanges = result.segments.filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.map { AudioTimeRangeCodable(try! AudioTimeRange(startOffsetSeconds: $0.startOffsetSeconds, endOffsetSeconds: $0.endOffsetSeconds)) }
        let raw = RawTranscription(schemaVersion: 1, sourcePath: file.path, sourceSHA256: hash, engine: engine.identifier, parameters: parameters, recordingStartLocal: try start.timestamp(atOffsetSeconds: 0), segments: result.segments, coverage: covered.map(AudioTimeRangeCodable.init), textRanges: textRanges, status: hasWords ? "completed_with_text" : "completed_no_text", accuracyAssessment: "not_evaluated")
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let rawData = try encoder.encode(raw)
        try AtomicFile.write(rawData, to: runDirectory.appendingPathComponent("raw.json"))
        if hasWords { let rendered = try render(raw: raw); try AtomicFile.write(Data(rendered.utf8), to: runDirectory.appendingPathComponent("transcript.md")) }
        return raw
    }
    public func render(raw: RawTranscription) throws -> String {
        let start = try RecordingStart(filename: URL(fileURLWithPath: raw.sourcePath).lastPathComponent)
        return raw.segments.filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.map { segment in
            let stamp = (try? start.timestamp(atOffsetSeconds: segment.startOffsetSeconds)) ?? raw.recordingStartLocal
            return "- [\(stamp)] \(segment.text)"
        }.joined(separator: "\n") + "\n"
    }
}

public struct FileProcessingResult: Sendable { public let file: URL; public let outputDirectory: URL; public let decision: ResumeDecision; public let failed: Bool
    public init(file: URL, outputDirectory: URL, decision: ResumeDecision, failed: Bool = false) { self.file = file; self.outputDirectory = outputDirectory; self.decision = decision; self.failed = failed }
}
public struct TranscriptionRun: Sendable {
    public let engine: any TranscriptionEngine
    public init(engine: any TranscriptionEngine) { self.engine = engine }
    public func process(files: [URL], runDirectory: URL, parameters: [String: String] = [:], forceRerun: Bool = false) async -> [FileProcessingResult] {
        var outcomes: [FileProcessingResult] = []
        for file in files {
            do {
                let hash = try SHA256.file(file), fingerprint = ResumeFingerprint(sourceSHA256: hash, engine: engine.identifier, parameters: parameters)
                let safeName = file.lastPathComponent.replacingOccurrences(of: "/", with: "_")
                let output = runDirectory.appendingPathComponent("\(hash.prefix(16))-\(safeName)", isDirectory: true)
                let statusURL = output.appendingPathComponent("status.json"), rawURL = output.appendingPathComponent("raw.json")
                let decision = forceRerun ? ResumeDecision.rerun("强制重跑") : ResumePlanner.plan(expected: fingerprint, statusURL: statusURL, rawURL: rawURL)
                if decision == .reuse { outcomes.append(FileProcessingResult(file: file, outputDirectory: output, decision: decision)); continue }
                var failed = false
                do {
                    let raw = try await TranscriptionPipeline(engine: engine).run(file: file, runDirectory: output, parameters: parameters)
                    let state: TranscriptionState = raw.status == "completed_with_text" ? .completedWithText : .completedNoText
                    let status = TranscriptionStatus(state: state, fingerprint: fingerprint)
                    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                    try AtomicFile.write(try encoder.encode(status), to: statusURL)
                } catch {
                    failed = true
                    let status = TranscriptionStatus(state: .failed, error: String(describing: error), fingerprint: fingerprint)
                    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                    try? AtomicFile.write(try encoder.encode(status), to: statusURL)
                }
                outcomes.append(FileProcessingResult(file: file, outputDirectory: output, decision: decision, failed: failed))
            } catch { outcomes.append(FileProcessingResult(file: file, outputDirectory: runDirectory, decision: .rerun("\(error)"), failed: true)) }
        }
        return outcomes
    }
}
