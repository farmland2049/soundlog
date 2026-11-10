import Foundation

/// Model for the batch acceptance summary file (记录/整理验收.json).
public struct BatchAcceptanceReport: Codable, Equatable, Sendable {
    public struct FileRecord: Codable, Equatable, Sendable {
        public let path: String
        public let status: String // "completed" or "failed"
        public let failureReason: String?
        public let modules: [String: String] // module name -> state

        public init(path: String, status: String, failureReason: String? = nil, modules: [String: String] = [:]) {
            self.path = path
            self.status = status
            self.failureReason = failureReason
            self.modules = modules
        }
    }

    public let schemaVersion: Int
    public let runTime: String
    public let inputPath: String
    public let isMock: Bool
    public let totalFiles: Int
    public let successCount: Int
    public let failureCount: Int
    public let successDefinition: String
    public let files: [FileRecord]

    public static let defaultSuccessDefinition = "所有必需模块（transcription, soundEvents, speakerDiarization, speakerAlignment, unifiedTranscript, inputCoverage, runManifest）均处于 completed 状态即视为成功（包括 mock 模式下 mock 引擎顺利完成）。若任一必需模块 failed 或 unsupported，或文件不可读/哈希失败，则判定为失败。"

    public init(
        schemaVersion: Int = 1,
        runTime: String,
        inputPath: String,
        isMock: Bool,
        totalFiles: Int,
        successCount: Int,
        failureCount: Int,
        successDefinition: String = defaultSuccessDefinition,
        files: [FileRecord]
    ) {
        self.schemaVersion = schemaVersion
        self.runTime = runTime
        self.inputPath = inputPath
        self.isMock = isMock
        self.totalFiles = totalFiles
        self.successCount = successCount
        self.failureCount = failureCount
        self.successDefinition = successDefinition
        self.files = files
    }

    /// Evaluates module states against required modules to determine success.
    public static func evaluateFileStatus(modules: [String: IntegratedModuleStatus]) -> (status: String, failureReason: String?, moduleStates: [String: String]) {
        let required = [
            "transcription",
            "soundEvents",
            "speakerDiarization",
            "speakerAlignment",
            "unifiedTranscript",
            "inputCoverage",
            "runManifest"
        ]
        var moduleStates: [String: String] = [:]
        for (k, v) in modules {
            moduleStates[k] = v.state
        }
        var failedIssues: [String] = []
        for req in required {
            guard let mod = modules[req] else {
                failedIssues.append("\(req): 缺失")
                continue
            }
            if mod.state != "completed" {
                let errStr = mod.error.map { " (\($0))" } ?? ""
                failedIssues.append("\(req): \(mod.state)\(errStr)")
            }
        }
        if let identMod = modules["speakerIdentities"], identMod.state == "failed" {
            let errStr = identMod.error.map { " (\($0))" } ?? ""
            failedIssues.append("speakerIdentities: failed\(errStr)")
        }
        if failedIssues.isEmpty {
            return (status: "completed", failureReason: nil, moduleStates: moduleStates)
        } else {
            return (status: "failed", failureReason: failedIssues.joined(separator: "; "), moduleStates: moduleStates)
        }
    }
}
