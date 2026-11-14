import Foundation
import Vision

struct TextRegion: Encodable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = CommandLine.arguments.contains("--fast") ? .fast : .accurate
let supported = Set(try request.supportedRecognitionLanguages())
request.recognitionLanguages = ["zh-Hans", "en-US"].filter { supported.contains($0) }
request.usesLanguageCorrection = false
let jpeg = FileHandle.standardInput.readDataToEndOfFile()
try VNImageRequestHandler(data: jpeg).perform([request])
let regions = (request.results ?? []).compactMap { observation -> TextRegion? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    return TextRegion(text: candidate.string, confidence: candidate.confidence,
                      x: observation.boundingBox.midX, y: 1 - observation.boundingBox.midY)
}
FileHandle.standardOutput.write(try JSONEncoder().encode(regions))
