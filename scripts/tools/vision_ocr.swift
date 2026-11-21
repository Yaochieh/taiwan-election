// macOS Vision OCR：輸入 PNG 路徑（多個），每張輸出一行 JSON
// {"file":..., "w":..., "h":..., "items":[{"t":..., "c":conf, "box":[x0,y0,x1,y1]}]}（像素座標，原點左上）
// 編譯：swiftc -O scripts/tools/vision_ocr.swift -o scripts/tools/vision_ocr
import Foundation
import Vision
import AppKit

for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("cannot load \(path)\n".data(using: .utf8)!); continue
    }
    let W = Double(cg.width), H = Double(cg.height)
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hant", "en-US"]
    req.usesLanguageCorrection = false
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    var items: [[String: Any]] = []
    for o in req.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        let b = o.boundingBox
        items.append(["t": c.string, "c": Double(c.confidence),
                      "box": [b.minX * W, (1 - b.maxY) * H, b.maxX * W, (1 - b.minY) * H]])
    }
    let obj: [String: Any] = ["file": path, "w": W, "h": H, "items": items]
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
}
