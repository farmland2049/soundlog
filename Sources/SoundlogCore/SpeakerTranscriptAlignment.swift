import Foundation

public struct SpeakerAlignedTranscriptEntry: Codable, Equatable, Sendable {
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double
    public let absoluteStartLocal: String
    public let absoluteEndLocal: String
    public let speakerCandidates: [String]
    public let hasUnattributedOverlap: Bool
    public let text: String
}

public struct SpeakerAlignedTranscriptDocument: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let sourcePath: String
    public let sourceSHA256: String
    public let recordingStartLocal: String
    public let transcriptionEngine: String
    public let diarizationEngine: String
    public let alignmentMethod: String
    public let accuracyAssessment: String
    public let segments: [SpeakerAlignedTranscriptEntry]
}

/// Associates transcript segments with anonymous speaker intervals by temporal
/// overlap. It deliberately preserves whole text segments and reports candidates.
public struct SpeakerTranscriptAlignmentPipeline: Sendable {
    public init() {}

    public func run(file: URL, runDirectory: URL) throws -> SpeakerAlignedTranscriptDocument {
        let rawURL = runDirectory.appendingPathComponent("raw.json")
        let speakerURL = runDirectory.appendingPathComponent("speaker-timeline.json")
        let raw = try JSONDecoder().decode(RawTranscription.self, from: Data(contentsOf: rawURL))
        let speakers = try JSONDecoder().decode(SpeakerTimelineDocument.self, from: Data(contentsOf: speakerURL))
        let actualHash = try SHA256.file(file)
        guard raw.sourceSHA256 == actualHash, speakers.sourceSHA256 == actualHash,
              raw.recordingStartLocal == speakers.recordingStartLocal else {
            throw TranscriptionError.io("转写与说话人结果的源文件或起始时间不一致")
        }

        let document = try Self.align(raw: raw, speakers: speakers, file: file)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try AtomicFile.write(try encoder.encode(document), to: runDirectory.appendingPathComponent("speaker-aligned-transcript.json"))
        try AtomicFile.write(Data(render(document: document, transcript: raw).utf8), to: runDirectory.appendingPathComponent("speaker-aligned-transcript.md"))
        return document
    }

    public static func align(raw: RawTranscription, speakers: SpeakerTimelineDocument, file: URL) throws -> SpeakerAlignedTranscriptDocument {
        guard raw.sourceSHA256 == speakers.sourceSHA256, raw.recordingStartLocal == speakers.recordingStartLocal else {
            throw TranscriptionError.io("转写与说话人结果的源文件或起始时间不一致")
        }
        let recordingStart: RecordingStart
        do { recordingStart = try RecordingStart(filename: file.lastPathComponent) }
        catch { throw TranscriptionError.invalidStartTime(file.lastPathComponent) }
        let entries = try raw.segments.compactMap { transcript -> SpeakerAlignedTranscriptEntry? in
            guard !transcript.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            let textRange = try AudioTimeRange(
                startOffsetSeconds: transcript.startOffsetSeconds,
                endOffsetSeconds: transcript.endOffsetSeconds
            )
            var candidates = Set<String>()
            var hasUnattributedOverlap = false
            for interval in speakers.segments {
                let overlap = min(textRange.endOffsetSeconds, interval.endOffsetSeconds)
                    - max(textRange.startOffsetSeconds, interval.startOffsetSeconds)
                guard overlap > 0 else { continue }
                if let speakerID = interval.speakerID { candidates.insert(speakerID) }
                else { hasUnattributedOverlap = true }
            }
            return SpeakerAlignedTranscriptEntry(
                startOffsetSeconds: textRange.startOffsetSeconds,
                endOffsetSeconds: textRange.endOffsetSeconds,
                absoluteStartLocal: try recordingStart.timestamp(atOffsetSeconds: textRange.startOffsetSeconds),
                absoluteEndLocal: try recordingStart.timestamp(atOffsetSeconds: textRange.endOffsetSeconds),
                speakerCandidates: candidates.sorted(),
                hasUnattributedOverlap: hasUnattributedOverlap,
                text: transcript.text
            )
        }

        return SpeakerAlignedTranscriptDocument(
            schemaVersion: 1,
            sourcePath: file.path,
            sourceSHA256: raw.sourceSHA256,
            recordingStartLocal: try recordingStart.timestamp(atOffsetSeconds: 0),
            transcriptionEngine: raw.engine,
            diarizationEngine: speakers.engine,
            alignmentMethod: "temporal_overlap_candidates",
            accuracyAssessment: "not_evaluated",
            segments: entries
        )
    }

    private func render(document: SpeakerAlignedTranscriptDocument, transcript: RawTranscription) -> String {
        var lines = ["# 说话人候选逐字稿", "", "- 录音起始：\(document.recordingStartLocal)", "- 时间依据：仅按转写区间与匿名说话人区间的时间重叠生成候选；未逐词切分，也未确认身份。", ""]
        if document.segments.isEmpty {
            lines.append("本次转写没有可关联的文字片段（\(transcript.status)）。")
        } else {
            for entry in document.segments {
                var labels = entry.speakerCandidates
                if entry.hasUnattributedOverlap { labels.append("未知") }
                let label = labels.isEmpty ? "未匹配" : labels.joined(separator: "、")
                lines.append("- [\(entry.absoluteStartLocal)–\(entry.absoluteEndLocal)] [候选说话人：\(label)] \(entry.text)")
            }
        }
        return lines.joined(separator: "\n") + "\n"
    }
}
