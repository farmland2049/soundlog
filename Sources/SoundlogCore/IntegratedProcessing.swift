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
