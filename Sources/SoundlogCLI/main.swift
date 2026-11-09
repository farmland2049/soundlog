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
                    func record(_ module: String, _ state: String, _ error: String? = nil, _ fingerprint: ResumeFingerprint? = nil) throws {
                        status.record(module, state: state, error: error, fingerprint: fingerprint)
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
                        else { anyFailed = true; try record("transcription", "failed", "转写管线失败；详情请查看同目录 status.json") }
                    } else {
                        anyFailed = true; try record("transcription", "unsupported", "需要 macOS 26 或更高版本")
                    }
                    }
                    #else
                    anyFailed = true; try record("transcription", "unsupported", "Speech/AVFoundation 不可用")
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
                    } catch { anyFailed = true; try record("soundEvents", "failed", String(describing: error)) }
                    #else
                    anyFailed = true; try record("soundEvents", "unsupported", "SoundAnalysis/AVFoundation 不可用")
                    #endif
                    }
                    #else
                    anyFailed = true; try record("soundEvents", "unsupported", "SoundAnalysis/AVFoundation 不可用")
                    #endif

                    let speakerFingerprint = ResumeFingerprint(sourceSHA256: hash, engine: "FluidAudio.OfflineVBx@0.17.7", parameters: [:])
                    let speakerArtifact = output.appendingPathComponent("speaker-timeline.json")
                    #if os(macOS)
                    let speakerDecision = IntegratedModuleResumePlanner.plan(expected: speakerFingerprint, status: status.modules["speakerDiarization"], artifactURL: speakerArtifact)
                    if speakerDecision == .reuse { try record("speakerDiarization", "completed", nil, speakerFingerprint) } else {
                    try record("speakerDiarization", "running", nil, speakerFingerprint)
                    #if os(macOS)
                    do {
                        _ = try await SpeakerTimelinePipeline(engine: FluidAudioSpeakerEngine()).run(file: file, runDirectory: output)
                        try record("speakerDiarization", "completed", nil, speakerFingerprint)
                    } catch { anyFailed = true; try record("speakerDiarization", "failed", String(describing: error)) }
                    #else
                    anyFailed = true; try record("speakerDiarization", "unsupported", "FluidAudio 仅支持 macOS")
                    #endif
                    }
                    #else
                    anyFailed = true; try record("speakerDiarization", "unsupported", "FluidAudio 仅支持 macOS")
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

