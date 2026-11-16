import Foundation
import AVFoundation
import CoreML

func fail(_ message: String) throws -> Never { throw NSError(domain: "SoundlogVoice", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
func run() throws {
 let args=CommandLine.arguments
 guard args.count==5, let start=Double(args[3]), let end=Double(args[4]), start.isFinite, end.isFinite, start>=0, end>start else { try fail("Expected model-directory audio-file start end") }
 let models=URL(fileURLWithPath:args[1],isDirectory:true), source=URL(fileURLWithPath:args[2])
 let file=try AVAudioFile(forReading:source,commonFormat:.pcmFormatFloat32,interleaved:false)
 let inputFormat=file.processingFormat
 let count=AVAudioFrameCount(min(10,end-start)*inputFormat.sampleRate)
 guard let input=AVAudioPCMBuffer(pcmFormat:inputFormat,frameCapacity:count), let format=AVAudioFormat(commonFormat:.pcmFormatFloat32,sampleRate:16000,channels:1,interleaved:false), let converter=AVAudioConverter(from:inputFormat,to:format) else { try fail("Audio converter unavailable") }
 file.framePosition=AVAudioFramePosition(start*inputFormat.sampleRate)
 try file.read(into:input,frameCount:count)
 guard input.frameLength>0 else { try fail("Empty audio interval") }
 let capacity=AVAudioFrameCount(ceil(Double(input.frameLength)*16000/inputFormat.sampleRate)+256)
 guard let output=AVAudioPCMBuffer(pcmFormat:format,frameCapacity:capacity) else { try fail("Output buffer unavailable") }
 var supplied=false; var error:NSError?
 let status=converter.convert(to:output,error:&error){ _, state in
  if supplied { state.pointee = .endOfStream;return nil }
  supplied=true;state.pointee = .haveData;return input
 }
 if let error=error { throw error }
 guard status != .error, let samples=output.floatChannelData?[0] else { try fail("Audio conversion failed") }
 let valid=min(Int(output.frameLength),160000)
 guard valid>=64000 else { try fail("At least four seconds of audio are required") }
 let waveform=try MLMultiArray(shape:[1,1,160000],dataType:.float32)
 // The fixed-window frontend centers features across the full window. Tiling a
 // short span avoids shifting its features with artificial digital silence.
 for i in 0..<160000 { waveform[i]=NSNumber(value:samples[i % valid]) }
 let configuration=MLModelConfiguration();configuration.computeUnits = .cpuOnly
 let fbank=try MLModel(contentsOf:models.appendingPathComponent("FBank.mlmodelc"),configuration:configuration)
 let backend=try MLModel(contentsOf:models.appendingPathComponent("Embedding.mlmodelc"),configuration:configuration)
 let features=try fbank.prediction(from:MLDictionaryFeatureProvider(dictionary:["audio":MLFeatureValue(multiArray:waveform)]))
 guard let bank=features.featureValue(for:"fbank_features") else { try fail("Missing fbank_features") }
 let weights=try MLMultiArray(shape:[1,589],dataType:.float32)
 for i in 0..<589 { weights[i]=NSNumber(value:Float(1)) }
 let result=try backend.prediction(from:MLDictionaryFeatureProvider(dictionary:["fbank_features":bank,"weights":MLFeatureValue(multiArray:weights)]))
 guard let vector=result.featureValue(for:"embedding")?.multiArrayValue else { try fail("Missing embedding") }
 let values=(0..<vector.count).map{vector[$0].doubleValue}
 let norm=sqrt(values.reduce(0){$0+$1*$1})
 guard norm>0, values.allSatisfy({$0.isFinite}) else { try fail("Invalid embedding") }
 let data=try JSONSerialization.data(withJSONObject:["embedding":values.map{$0/norm},"dimension":values.count,"usedStart":start,"usedEnd":start+Double(valid)/16000,"engine":"local-coreml-community1-v1","scope":"anonymous acoustic feature; not a confirmed identity"])
 FileHandle.standardOutput.write(data)
}
do { try run() } catch { FileHandle.standardError.write(Data((error.localizedDescription+"\n").utf8));exit(1) }
