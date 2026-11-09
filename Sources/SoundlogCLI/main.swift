import Foundation
import SoundlogCore

@main struct SoundlogCLI {
    static func main() async {
        do {
            let options = try CLIOptions.parse(Array(CommandLine.arguments.dropFirst()))
            let files = try InputEnumerator.files(at: options.input)
            let run = options.runDirectory ?? options.outputRoot.appendingPathComponent("run-\(ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-") )-\(UUID().uuidString.prefix(8))", isDirectory: true)
            try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
            let manifest = try InputEnumerator.manifest(at: options.input)
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try AtomicFile.write(try encoder.encode(manifest), to: run.appendingPathComponent("manifest.json"))
            if options.command == .manifest { print("清单已写入: \(run.path)"); return }
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
            let engine = AppleSpeechEngine(localeIdentifier: options.parameters["locale"] ?? "zh-CN")
            let outcomes = await TranscriptionRun(engine: engine).process(files: files, runDirectory: run, parameters: options.parameters)
            for outcome in outcomes { if case .rerun(let reason) = outcome.decision, reason != "无记录" { fputs("转写处理 \(outcome.file.lastPathComponent): \(reason)\n", stderr) } }
            if TranscriptionExitStatus.exitCode(for: outcomes) != 0 { exit(1) }
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

