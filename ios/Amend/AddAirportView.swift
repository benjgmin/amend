import SwiftUI

struct AddAirportView: View {
    @Environment(AirportStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @FocusState private var focused: Bool

    private var results: [AirportInfo] { store.search(query) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass").foregroundStyle(EFB.dim)
                    TextField("", text: $query, prompt: Text("ID, ICAO, NAME OR CITY").foregroundStyle(EFB.faint))
                        .font(EFB.mono(16, .semibold))
                        .foregroundStyle(EFB.text)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .focused($focused)
                        .onSubmit(addTopResult)
                }
                .padding(12)
                .background(EFB.panelHi, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(EFB.cyan.opacity(0.4), lineWidth: 1))
                .padding()

                List {
                    ForEach(results) { apt in
                        Button { add(apt.id) } label: { ResultRow(apt: apt, saved: store.isSaved(apt.id)) }
                            .efbRow(top: 2, bottom: 2)
                    }
                    // not in the directory (or directory not loaded yet): allow adding the raw id
                    if results.isEmpty, let id = AirportStore.normalize(query) {
                        Button { add(id) } label: {
                            Text("ADD \(id)")
                                .font(EFB.mono(14, .bold))
                                .foregroundStyle(EFB.cyan)
                                .efbPanel()
                        }
                        .efbRow()
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
            .background(EFB.bg)
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(EFB.bg, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("ADD AIRPORT")
                        .font(EFB.mono(15, .bold))
                        .tracking(2)
                        .foregroundStyle(EFB.text)
                }
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
            }
            .onAppear { focused = true }
        }
    }

    private func add(_ id: String) {
        store.add(id)
        dismiss()
    }

    private func addTopResult() {
        if let first = results.first {
            add(first.id)
        } else if let id = AirportStore.normalize(query) {
            add(id)
        }
    }
}

private struct ResultRow: View {
    let apt: AirportInfo
    let saved: Bool

    var body: some View {
        HStack(spacing: 12) {
            Text(apt.id)
                .font(EFB.mono(16, .bold))
                .foregroundStyle(EFB.text)
                .frame(width: 56, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(apt.name)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(EFB.text.opacity(0.9))
                    .lineLimit(1)
                Text([apt.icao, apt.location.isEmpty ? nil : apt.location.uppercased(),
                      apt.type == "airport" ? nil : apt.type?.uppercased()]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(EFB.mono(10))
                    .foregroundStyle(EFB.dim)
                    .lineLimit(1)
            }
            Spacer()
            if saved {
                Image(systemName: "checkmark").foregroundStyle(EFB.green)
            }
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(EFB.panel, in: RoundedRectangle(cornerRadius: 6))
    }
}
