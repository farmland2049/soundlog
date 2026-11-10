import Foundation
import SoundlogCore

@main struct SoundlogCLI {
    static func main() async {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments == ["speaker-models", "install"] {
            #if os(macOS)
            do {
                let receipt = try await FluidAudioSpeakerEngine.installAndValidateModels()
                let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                print(String(decoding: try encoder.encode(receipt), as: UTF8.self))
                return
            } catch {
                FileHandle.standardError.write(Data("说话人模型安装或校验失败: \(error)\n".utf8)); exit(1)
            }
            #else
            FileHandle.standardError.write(Data("错误: FluidAudio 说话人模型仅支持 macOS。\n".utf8)); exit(2)
            #endif
        }
        do {
            let options = try CLIOptions.parse(arguments)
            let files = try InputEnumerator.files(at: options.input)
            let run = options.runDirectory ?? options.outputRoot.appendingPathComponent("run-\(ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-") )-\(UUID().uuidString.prefix(8))", isDirectory: true)
            try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
            let manifest = try InputEnumerator.manifest(at: options.input)
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try AtomicFile.write(try encoder.encode(manifest), to: run.appendingPathComponent("manifest.json"))
            if options.command == .manifest { print("清单已写入: \(run.path)"); return }
            if options.command == .process {
                let processStart = Date()
                let allowed = Set(["locale", "confidenceThreshold", "minimumEventDurationSeconds", "mergeGapSeconds"])
                if let unknown = options.parameters.keys.first(where: { !allowed.contains($0) }) {
                    throw TranscriptionError.usage("process 不支持参数: \(unknown)")
                }
                let diarizationParameters = try SoundEventParameterParser.parse(options.parameters.filter { $0.key != "locale" })
                var anyFailed = false
                for file in files {
                    let hash = try SHA256.file(file)
                    let safeName = file.lastPathComponent.replacingOccurrences(of: "/", with: "_")
                    let output = run.appendingPathComponent("\(hash.prefix(16))-\(safeName)", isDirectory: true)
                    try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
                    let statusURL = output.appendingPathComponent("processing-status.json")
                    var status = (try? JSONDecoder().decode(IntegratedProcessingStatus.self, from: Data(contentsOf: statusURL)))
                        .flatMap { $0.sourceSHA256 == hash ? $0 : nil }
                        ?? IntegratedProcessingStatus(sourcePath: file.path, sourceSHA256: hash)
                    var moduleStarts: [String: Date] = [:]
                    func record(_ module: String, _ state: String, _ error: String? = nil, _ fingerprint: ResumeFingerprint? = nil) throws {
                        status.record(module, state: state, error: error, fingerprint: fingerprint)
                        if state == "running" { moduleStarts[module] = Date() }
                        else if let start = moduleStarts.removeValue(forKey: module) {
                            status.modules[module]?.wallClockSeconds = Date().timeIntervalSince(start)
                            status.modules[module]?.execution = "recomputed"
                        } else if state == "completed" {
                            status.modules[module]?.execution = "recomputed"
                            status.modules[module]?.wallClockSeconds = 0
                        } else if ["failed", "unsupported", "skipped"].contains(state) {
                            status.modules[module]?.execution = state == "skipped" ? "skip" : state
                            status.modules[module]?.wallClockSeconds = 0
                        }
                        try IntegratedArtifactValidator.validate(status: status)
                        try AtomicFile.write(try encoder.encode(status), to: output.appendingPathComponent("processing-status.json"))
                    }
                    let locale = options.parameters["locale"] ?? "zh-CN"
                    let transcriptionFingerprint = ResumeFingerprint(sourceSHA256: hash, engine: "apple-speech-analyzer", parameters: ["locale": locale])
                    let rawArtifact = output.appendingPathComponent("raw.json")
                    #if canImport(Speech) && canImport(AVFoundation)
                    let transcriptionDecision = IntegratedModuleResumePlanner.plan(expected: transcriptionFingerprint, status: status.modules["transcription"], artifactURL: rawArtifact)
                    if transcriptionDecision == .reuse { try record("transcription", "completed", nil, transcriptionFingerprint) }
                    else {
                    try record("transcription", "running", nil, transcriptionFingerprint)
                    if #available(macOS 26.0, *) {
                        let engine = AppleSpeechEngine(localeIdentifier: locale)
                        let outcomes = await TranscriptionRun(engine: engine).process(files: [file], runDirectory: run, parameters: ["locale": locale])
                        if let result = outcomes.first, !result.failed { try record("transcription", "completed", nil, transcriptionFingerprint) }
                        else { anyFailed = true; try record("transcription", "failed", "转写管线失败；详情请查看同目录 status.json", transcriptionFingerprint) }
                    } else {
                        anyFailed = true; try record("transcription", "unsupported", "需要 macOS 26 或更高版本", transcriptionFingerprint)
                    }
                    }
                    #else
                    anyFailed = true; try record("transcription", "unsupported", "Speech/AVFoundation 不可用", transcriptionFingerprint)
                    #endif

                    let soundFingerprint = ResumeFingerprint(sourceSHA256: hash, engine: "apple-sound-analysis-version1", parameters: ["confidenceThreshold": String(diarizationParameters.confidenceThreshold), "minimumEventDurationSeconds": String(diarizationParameters.minimumEventDurationSeconds), "mergeGapSeconds": String(diarizationParameters.mergeGapSeconds)])
                    let soundArtifact = output.appendingPathComponent("sound-events.json")
                    #if canImport(SoundAnalysis) && canImport(AVFoundation)
                    let soundDecision = IntegratedModuleResumePlanner.plan(expected: soundFingerprint, status: status.modules["soundEvents"], artifactURL: soundArtifact)
                    if soundDecision == .reuse { try record("soundEvents", "completed", nil, soundFingerprint) } else {
                    try record("soundEvents", "running", nil, soundFingerprint)
                    #if canImport(SoundAnalysis) && canImport(AVFoundation)
                    do {
                        _ = try await SoundEventPipeline(engine: AppleSoundEventEngine()).run(file: file, runDirectory: output, parameters: diarizationParameters)
                        try record("soundEvents", "completed", nil, soundFingerprint)
                    } catch { anyFailed = true; try record("soundEvents", "failed", String(describing: error), soundFingerprint) }
                    #else
                    anyFailed = true; try record("soundEvents", "unsupported", "SoundAnalysis/AVFoundation 不可用", soundFingerprint)
                    #endif
                    }
                    #else
                    anyFailed = true; try record("soundEvents", "unsupported", "SoundAnalysis/AVFoundation 不可用", soundFingerprint)
                    #endif

                    let speakerFingerprint = ResumeFingerprint(sourceSHA256: hash, engine: "FluidAudio.OfflineVBx@0.17.7", parameters: [:])
                    let speakerArtifact = output.appendingPathComponent("speaker-timeline.json")
                    #if os(macOS)
                    let speakerDecision = IntegratedModuleResumePlanner.plan(expected: speakerFingerprint, status: status.modules["speakerDiarization"], artifactURL: speakerArtifact)
                    if speakerDecision == .reuse { try record("speakerDiarization", "completed", nil, speakerFingerprint) } else {
                    #if os(macOS)
                    let completed = await IntegratedModuleExecutor.execute(module: "speakerDiarization", fingerprint: speakerFingerprint, status: &status, statusURL: statusURL, encoder: encoder) {
                        _ = try await SpeakerTimelinePipeline(engine: FluidAudioSpeakerEngine()).run(file: file, runDirectory: output)
                    }
                    if !completed { anyFailed = true }
                    #else
                    anyFailed = true; try record("speakerDiarization", "unsupported", "FluidAudio 仅支持 macOS", speakerFingerprint)
                    #endif
                    }
                    #else
                    anyFailed = true; try record("speakerDiarization", "unsupported", "FluidAudio 仅支持 macOS", speakerFingerprint)
                    #endif

                    let alignmentFingerprint = ResumeFingerprint(sourceSHA256: hash, engine: "temporal_overlap_candidates", parameters: ["transcription": options.parameters["locale"] ?? "zh-CN", "diarization": speakerFingerprint.engine])
                    let alignmentArtifact = output.appendingPathComponent("speaker-aligned-transcript.json")
                    if status.modules["transcription"]?.state == "completed",
                       status.modules["speakerDiarization"]?.state == "completed" {
                        let decision = IntegratedModuleResumePlanner.plan(expected: alignmentFingerprint, status: status.modules["speakerAlignment"], artifactURL: alignmentArtifact)
                        if decision == .reuse { try record("speakerAlignment", "completed", nil, alignmentFingerprint) }
                        else {
                            try record("speakerAlignment", "running", nil, alignmentFingerprint)
                            do {
                                _ = try SpeakerTranscriptAlignmentPipeline().run(file: file, runDirectory: output)
                                try record("speakerAlignment", "completed", nil, alignmentFingerprint)
                            } catch { anyFailed = true; try record("speakerAlignment", "failed", String(describing: error), alignmentFingerprint) }
                        }
                    } else {
                        try record("speakerAlignment", "skipped", "转写或说话人分离未完成")
                    }
                    // Render one user-facing transcript and a hash-indexed run manifest from
                    // whatever modules completed. A module failure never suppresses these.
                    var artifactURLs: [String: URL] = [:]
                    let candidatesURL = output.appendingPathComponent("speaker-aligned-transcript.json")
                    if let data = try? Data(contentsOf: candidatesURL),
                       let document = try? JSONDecoder().decode(SpeakerAlignedTranscriptDocument.self, from: data) {
                        for ext in ["md", "txt"] {
                            let url = output.appendingPathComponent("transcript-with-speaker-candidates.\(ext)")
                            do {
                                let unifiedFingerprint = ResumeFingerprint(sourceSHA256: hash, engine: "unified-candidate-renderer-v1", parameters: ["format": ext])
                                try UnifiedOutput.writeTranscript(document, format: ext, to: url, status: &status, statusURL: statusURL, fingerprint: unifiedFingerprint, encoder: encoder)
                                artifactURLs["transcript-\(ext)"] = url
                            } catch { anyFailed = true }
                        }
                    } else {
                        try record("unifiedTranscript", "skipped", "没有可用候选对齐结果")
                    }
                    let durationInfo = (try? UnifiedOutput.audioDuration(file: file)) ?? AudioDuration(seconds: nil, method: "failed", error: "无法读取输入")
                    let duration = durationInfo.seconds
                    var ranges: [AudioTimeRange] = []
                    if let rawData = try? Data(contentsOf: output.appendingPathComponent("raw.json")), let raw = try? JSONDecoder().decode(RawTranscription.self, from: rawData) {
                        ranges += raw.coverage.compactMap { try? AudioTimeRange(startOffsetSeconds: $0.start, endOffsetSeconds: $0.end) }
                        artifactURLs["transcription-raw"] = output.appendingPathComponent("raw.json")
                    }
                    for name in ["sound-events.json", "speaker-timeline.json", "speaker-aligned-transcript.json"] {
                        let url = output.appendingPathComponent(name)
                        if FileManager.default.fileExists(atPath: url.path) { artifactURLs[name] = url }
                    }
                    for name in ["speaker-aligned-transcript.md", "status.json"] {
                        let url = output.appendingPathComponent(name)
                        if FileManager.default.fileExists(atPath: url.path) { artifactURLs[name] = url }
                    }
                    if let duration, let coverage = try? UnifiedOutput.coverageReport(ranges: ranges, duration: duration), coverage.gaps.isEmpty {
                        try record("inputCoverage", "completed")
                    } else if duration != nil { try record("inputCoverage", "incomplete", "覆盖存在缺口或无转写覆盖") }
                    let sampleMap = Dictionary(uniqueKeysWithValues: artifactURLs.compactMap { key, url -> (String, [String])? in
                        guard let data = try? Data(contentsOf: url) else { return nil }
                        if key == "transcription-raw", let raw = try? JSONDecoder().decode(RawTranscription.self, from: data) {
                            return (key, raw.segments.map { "\($0.startOffsetSeconds)-\($0.endOffsetSeconds): \($0.text)" })
                        }
                        if key == "speaker-timeline.json", let doc = try? JSONDecoder().decode(SpeakerTimelineDocument.self, from: data) {
                            return (key, doc.segments.map { segment in
                                let label = segment.speakerID ?? "未匹配"
                                return "\(segment.startOffsetSeconds)-\(segment.endOffsetSeconds): \(label)"
                            })
                        }
                        if key == "speaker-aligned-transcript.json", let doc = try? JSONDecoder().decode(SpeakerAlignedTranscriptDocument.self, from: data) {
                            return (key, doc.segments.map { segment in
                                let labels = UnifiedOutput.candidateLabels(segment)
                                let candidates = labels.isEmpty ? "未匹配" : labels.joined(separator: "、")
                                return "\(segment.absoluteStartLocal): [\(candidates)] \(segment.text)"
                            })
                        }
                        if key == "sound-events.json", let doc = try? JSONDecoder().decode(SoundEventsDocument.self, from: data) {
                            return (key, doc.events.map { "\($0.startOffsetSeconds)-\($0.endOffsetSeconds): \($0.category)" })
                        }
                        return nil
                    })
                    do {
                        let memory = ProcessPeakMemory.current()
                        let performance = RunPerformance(wallClockSeconds: Date().timeIntervalSince(processStart), peakMemoryBytes: memory.bytes, peakMemorySource: memory.source, ruMaxRSSUnit: memory.unit)
                        try UnifiedOutput.writeManifest(inputPath: file.path, sourceSHA256: hash, duration: duration, coverageRanges: ranges, modules: status.modules, samples: sampleMap, artifactURLs: artifactURLs, baseDirectory: output, to: output.appendingPathComponent("run-manifest.json"), encoder: encoder, durationMethod: durationInfo.method, durationError: durationInfo.error, performance: performance)
                        try record("runManifest", "completed", nil, ResumeFingerprint(sourceSHA256: hash, engine: "run-manifest-v1", parameters: [:]))
                    } catch {
                        anyFailed = true
                        try? record("runManifest", "failed", String(describing: error), ResumeFingerprint(sourceSHA256: hash, engine: "run-manifest-v1", parameters: [:]))
                    }
                    print("三类分析结束: \(output.path)")
                }
                if anyFailed { exit(1) }
                return
            }
            if options.command == .speakerDiarize {
                #if os(macOS)
                let engine = FluidAudioSpeakerEngine()
                var failed = false
                for file in files {
                    let hash = try SHA256.file(file)
                    let output = run.appendingPathComponent("\(hash.prefix(16))-\(file.lastPathComponent)", isDirectory: true)
                    do {
                        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
                        _ = try await SpeakerTimelinePipeline(engine: engine).run(file: file, runDirectory: output)
                        print("匿名说话人时间线已写入: \(output.path)")
                    } catch {
                        failed = true
                        fputs("说话人分离 \(file.lastPathComponent) 失败: \(error)\n", stderr)
                    }
                }
                if failed { exit(1) }
                return
                #else
                FileHandle.standardError.write(Data("错误: FluidAudio 说话人分离仅支持 macOS。\n".utf8)); exit(2)
                #endif
            }
            if options.command == .soundEvents {
                let parameters = try SoundEventParameterParser.parse(options.parameters)
                #if canImport(SoundAnalysis) && canImport(AVFoundation)
                let engine = AppleSoundEventEngine()
                var failed = false
                for file in files {
                    let hash = try SHA256.file(file)
                    let output = run.appendingPathComponent("\(hash.prefix(16))-\(file.lastPathComponent)", isDirectory: true)
                    do { _ = try await SoundEventPipeline(engine: engine).run(file: file, runDirectory: output, parameters: parameters); print("声音事件已写入: \(output.path)") }
                    catch { failed = true; fputs("声音事件处理 \(file.lastPathComponent) 失败: \(error)\n", stderr) }
                }
                if failed { exit(1) }
                #else
                FileHandle.standardError.write(Data("错误: 本平台不支持 SoundAnalysis 声音分类。\n".utf8)); exit(2)
                #endif
                #if canImport(SoundAnalysis) && canImport(AVFoundation)
                return
                #endif
            }
            #if canImport(Speech) && canImport(AVFoundation)
            if #available(macOS 26.0, *) {
                let engine = AppleSpeechEngine(localeIdentifier: options.parameters["locale"] ?? "zh-CN")
                let outcomes = await TranscriptionRun(engine: engine).process(files: files, runDirectory: run, parameters: options.parameters)
                for outcome in outcomes { if case .rerun(let reason) = outcome.decision, reason != "无记录" { fputs("转写处理 \(outcome.file.lastPathComponent): \(reason)\n", stderr) } }
                if TranscriptionExitStatus.exitCode(for: outcomes) != 0 { exit(1) }
            } else {
                throw TranscriptionError.unsupportedPlatform
            }
            #else
            _ = files
            FileHandle.standardError.write(Data("错误: 本平台不支持苹果转写（Speech/AVFoundation 不可用）。清单已写入: \(run.path)\n".utf8))
            exit(2)
            #endif
        } catch {
            FileHandle.standardError.write(Data("错误: \(error)\n".utf8)); exit(2)
        }
    }
}

