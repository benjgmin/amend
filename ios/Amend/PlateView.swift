
import PDFKit
import SwiftUI

/// A chart (approach plate, diagram...) the user wants to open inside the app.
struct Plate: Identifiable {
    let url: URL
    let title: String
    var id: URL { url }
}

/// In-app plate viewer: downloads the FAA PDF and shows it with pinch-to-zoom.
/// The share button saves it to Files or opens it in another app (ForeFlight, etc.).
struct PlateView: View {
    let plate: Plate
    @Environment(\.dismiss) private var dismiss
    @State private var document: PDFDocument?
    @State private var fileURL: URL?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            ZStack {
                EFB.bg.ignoresSafeArea()
                if let document {
                    PDFKitView(document: document)
                        .ignoresSafeArea(edges: .bottom)
                } else if let error {
                    ContentUnavailableView("Couldn't load the chart", systemImage: "doc.questionmark",
                                           description: Text(error))
                } else {
                    ProgressView("Loading chart…")
                        .foregroundStyle(EFB.dim)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(EFB.bg, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text(plate.title.uppercased())
                        .font(EFB.mono(13, .bold))
                        .foregroundStyle(EFB.text)
                        .lineLimit(1)
                }
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    if let fileURL {
                        ShareLink(item: fileURL) { Image(systemName: "square.and.arrow.up") }
                    }
                }
            }
            .task { await load() }
        }
    }

    private func load() async {
        do {
            let (data, response) = try await URLSession.shared.data(from: plate.url)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                throw APIError.badStatus(http.statusCode)
            }
            guard let doc = PDFDocument(data: data) else {
                error = "The FAA returned something that isn't a PDF."
                return
            }
            // keep a named copy so sharing gives "ILS OR LOC RWY 07L.pdf", not a random name
            let safe = plate.title.replacingOccurrences(of: "/", with: "-")
            let file = FileManager.default.temporaryDirectory.appending(path: "\(safe).pdf")
            try? data.write(to: file, options: .atomic)
            fileURL = file
            document = doc
        } catch {
            self.error = error.localizedDescription
        }
    }
}

private struct PDFKitView: UIViewRepresentable {
    let document: PDFDocument

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.document = document
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.backgroundColor = UIColor(EFB.bg)
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document !== document { view.document = document }
    }
}
