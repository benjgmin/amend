import SwiftUI

struct AddAirportView: View {
    @Environment(AirportStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    /// true when opened to choose the home airport (welcome screen); otherwise adding never sets home
    var makeHome = false
    @State private var query = ""
    @FocusState private var focused: Bool

    private var results: [AirportInfo] { store.search(query) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass").foregroundStyle(EFB.dim)
                    TextField("", text: $query, prompt: Text("ID, ICAO, name or city").foregroundStyle(EFB.faint))
                        .font(.system(size: 16))
                        .foregroundStyle(EFB.text)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .focused($focused)
                        .onSubmit(addTopResult)
                }
                .padding(12)
                .background(EFB.panelHi, in: RoundedRectangle(cornerRadius: 12))
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
                            Text("Add \(id)")
                                .font(.system(size: 15, weight: .semibold))
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
                    Text(makeHome ? "Choose home airport" : "Add airport")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(EFB.text)
                }
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
            }
            .onAppear { focused = true }
        }
    }

    private func add(_ id: String) {
        if let id = store.add(id), makeHome { store.setHome(id) }
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
                Text([apt.icao, apt.location.isEmpty ? nil : apt.location,
                      apt.type == "airport" ? nil : apt.type?.capitalized]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(.system(size: 12.5))
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
