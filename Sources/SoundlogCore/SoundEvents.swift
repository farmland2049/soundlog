import Foundation

public struct SoundEventCandidate: Codable, Equatable, Sendable {
    public let category: String
    public let confidence: Double
    public init(category: String, confidence: Double) { self.category = category; self.confidence = confidence }
}

public struct SoundClassificationWindow: Codable, Equatable, Sendable {
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double
    public let candidates: [SoundEventCandidate]
    public let classificationStatus: String
    public init(start: Double, end: Double, candidates: [SoundEventCandidate], classificationStatus: String = "unclassified") {
        startOffsetSeconds = start; endOffsetSeconds = end; self.candidates = candidates; self.classificationStatus = classificationStatus
    }
}

public struct SoundEventParameters: Codable, Equatable, Sendable {
    public let confidenceThreshold: Double
    public let minimumEventDurationSeconds: Double
    public let mergeGapSeconds: Double
    public init(confidenceThreshold: Double = 0.3, minimumEventDurationSeconds: Double = 0.5, mergeGapSeconds: Double = 0.5) {
        self.confidenceThreshold = confidenceThreshold; self.minimumEventDurationSeconds = minimumEventDurationSeconds; self.mergeGapSeconds = mergeGapSeconds
    }
}

public enum SoundEventParameterParser {
    public static func parse(_ values: [String: String]) throws -> SoundEventParameters {
        let allowed: Set<String> = ["confidenceThreshold", "minimumEventDurationSeconds", "mergeGapSeconds"]
        for key in values.keys where !allowed.contains(key) { throw TranscriptionError.usage("未知声音事件参数: \(key)") }
        func number(_ key: String, default fallback: Double) throws -> Double {
            guard let raw = values[key] else { return fallback }
            guard let value = Double(raw), value.isFinite else { throw TranscriptionError.usage("声音事件参数 \(key) 必须是有限数字") }
            return value
        }
        let result = SoundEventParameters(confidenceThreshold: try number("confidenceThreshold", default: 0.3),
            minimumEventDurationSeconds: try number("minimumEventDurationSeconds", default: 0.5),
            mergeGapSeconds: try number("mergeGapSeconds", default: 0.5))
        guard (0...1).contains(result.confidenceThreshold), result.minimumEventDurationSeconds >= 0, result.mergeGapSeconds >= 0 else {
            throw TranscriptionError.usage("声音事件参数超出范围")
        }
        return result
    }
}

public struct SoundEvent: Codable, Equatable, Sendable {
    public let category: String
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double
    public let sourceWindowIndices: [Int]
    public let absoluteStartLocal: String
    public let absoluteEndLocal: String
}

public struct SoundEventsDocument: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let sourcePath: String
    public let sourceSHA256: String
    public let recordingStartLocal: String
    public let engine: String
    public let parameters: SoundEventParameters
    public let windows: [SoundClassificationWindow]
    public let events: [SoundEvent]
    public let windowBoundaryCaveat: String
    public let inferenceBoundary: String
}

public enum SoundEventBuilder {
    public static func events(windows: [SoundClassificationWindow], parameters: SoundEventParameters, recordingStart: RecordingStart) throws -> [SoundEvent] {
        guard parameters.confidenceThreshold.isFinite, (0...1).contains(parameters.confidenceThreshold),
              parameters.minimumEventDurationSeconds.isFinite, parameters.minimumEventDurationSeconds >= 0,
              parameters.mergeGapSeconds.isFinite, parameters.mergeGapSeconds >= 0 else { throw TimelineError.invalidRange }
        for window in windows {
            _ = try AudioTimeRange(startOffsetSeconds: window.startOffsetSeconds, endOffsetSeconds: window.endOffsetSeconds)
            for candidate in window.candidates where !candidate.confidence.isFinite || !(0...1).contains(candidate.confidence) { throw TimelineError.invalidRange }
        }
        var byCategory: [String: [(Int, SoundClassificationWindow)]] = [:]
        for (index, window) in windows.enumerated() {
            let qualified = window.candidates.filter { $0.confidence >= parameters.confidenceThreshold }
            if qualified.isEmpty { byCategory["unknown", default: []].append((index, window)) }
            else { for category in Set(qualified.map(\.category)) { byCategory[category, default: []].append((index, window)) } }
        }
        var result: [SoundEvent] = []
        for (category, entries) in byCategory {
            let sorted = entries.sorted { $0.1.startOffsetSeconds < $1.1.startOffsetSeconds }
            var group: [(Int, SoundClassificationWindow)] = []
            func appendGroup() throws {
                guard let first = group.first?.1, let last = group.map(\.1).max(by: { $0.endOffsetSeconds < $1.endOffsetSeconds }) else { return }
                let duration = last.endOffsetSeconds - first.startOffsetSeconds
                if duration >= parameters.minimumEventDurationSeconds {
                    result.append(SoundEvent(category: category, startOffsetSeconds: first.startOffsetSeconds, endOffsetSeconds: last.endOffsetSeconds,
                        sourceWindowIndices: group.map(\.0), absoluteStartLocal: try recordingStart.timestamp(atOffsetSeconds: first.startOffsetSeconds),
                        absoluteEndLocal: try recordingStart.timestamp(atOffsetSeconds: last.endOffsetSeconds)))
                }
            }
            for entry in sorted {
                if let last = group.map(\.1).max(by: { $0.endOffsetSeconds < $1.endOffsetSeconds }), entry.1.startOffsetSeconds - last.endOffsetSeconds > parameters.mergeGapSeconds {
                    try appendGroup(); group = []
                }
                group.append(entry)
            }
            try appendGroup()
        }
        return result.sorted { ($0.startOffsetSeconds, $0.category) < ($1.startOffsetSeconds, $1.category) }
    }
}

public struct SoundEventEngineResult: Sendable { public let windows: [SoundClassificationWindow]; public init(windows: [SoundClassificationWindow]) { self.windows = windows } }
public protocol SoundEventEngine: Sendable { var identifier: String { get }; func classify(file: URL) async throws -> SoundEventEngineResult }

public struct SoundEventPipeline: Sendable {
    public let engine: any SoundEventEngine
    public init(engine: any SoundEventEngine) { self.engine = engine }
    public func run(file: URL, runDirectory: URL, parameters: SoundEventParameters = SoundEventParameters()) async throws -> SoundEventsDocument {
        let start: RecordingStart
        do { start = try RecordingStart(filename: file.lastPathComponent) } catch { throw TranscriptionError.invalidStartTime(file.lastPathComponent) }
        let result = try await engine.classify(file: file)
        let windows = result.windows.map { window in
            SoundClassificationWindow(start: window.startOffsetSeconds, end: window.endOffsetSeconds, candidates: window.candidates,
                classificationStatus: window.candidates.contains { $0.confidence >= parameters.confidenceThreshold } ? "classified" : "unknown")
        }
        let document = SoundEventsDocument(schemaVersion: 1, sourcePath: file.path, sourceSHA256: try SHA256.file(file),
            recordingStartLocal: try start.timestamp(atOffsetSeconds: 0), engine: engine.identifier, parameters: parameters,
            windows: windows, events: try SoundEventBuilder.events(windows: windows, parameters: parameters, recordingStart: start),
            windowBoundaryCaveat: "分类窗口边界不等于真实事件的精确起止时间。", inferenceBoundary: "候选不自动确认地点、活动或声音来自现场还是外放。")
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try AtomicFile.write(try encoder.encode(document), to: runDirectory.appendingPathComponent("sound-events.json"))
        return document
    }
}

public enum TranscriptionExitStatus {
    public static func exitCode(for outcomes: [FileProcessingResult]) -> Int { outcomes.contains(where: \.failed) ? 1 : 0 }
}
