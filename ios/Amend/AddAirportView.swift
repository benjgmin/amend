import SwiftUI

/// search every US airport. Tapping a result opens its page (look without adding, like amend.watch);
/// + / ✓ puts it on or takes it off your airports. Opened to choose a home field (welcome screen), a tap picks it.
struct AddAirportView: View {
    @Environment(AirportStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    /// true when opened to choose the home airport (welcome screen); otherwise adding never sets home
    var makeHome = false
    @State private var path: [String] = []
    @State private var query = ""
    @FocusState private var focused: Bool

    private var results: [AirportInfo] { store.search(query) }

    var body: some View {
        NavigationStack(path: $path) {
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
                    if !makeHome, store.lists.count > 1, let list = store.activeList, !results.isEmpty {
                        Text("Tap + to add to \(list.name). Switch lists on the home screen.")
                            .font(.footnote)
                            .foregroundStyle(EFB.faint)
                            .efbRow(top: 0, bottom: 4)
                    }
                    // before you type: the busiest airports this cycle, so the sheet isn't blank
                    if query.trimmingCharacters(in: .whitespaces).isEmpty, !makeHome, !store.busiest.isEmpty {
                        EFBHeader(text: "Most action items this cycle").efbRow(top: 0, bottom: 2)
                        ForEach(store.busiest, id: \.self) { id in
                            if let apt = store.info(for: id) {
                                HStack(spacing: 8) {
                                    Button { open(id) } label: {
                                        ResultRow(apt: apt, counts: store.counts(for: id), indexLoaded: store.index != nil)
                                    }
                                    .buttonStyle(.plain)
                                    toggle(id)
                                }
                                .efbRow(top: 2, bottom: 2)
                            }
                        }
                    }
                    ForEach(results) { apt in
                        HStack(spacing: 8) {
                            Button { open(apt.id) } label: {
                                ResultRow(apt: apt, counts: store.counts(for: apt.id), indexLoaded: store.index != nil)
                            }
                            .buttonStyle(.plain)
                            if !makeHome { toggle(apt.id) }
                        }
                        .efbRow(top: 2, bottom: 2)
                    }
                    // not in the directory (or directory not loaded yet): allow adding the raw id
                    if results.isEmpty, let id = AirportStore.normalize(query) {
                        Button { makeHome ? pick(id) : open(id) } label: {
                            Text(makeHome ? "Make \(id) home" : "Open \(id)")
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
                    Text(makeHome ? "Choose home airport" : "Search airports")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(EFB.text)
                }
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
            }
            .navigationDestination(for: String.self) { AirportDetailView(id: $0) }
            .onAppear { if path.isEmpty { focused = true } }
        }
    }

    /// + puts it on the list in use (starting "My airports" if there's none), ✓ takes it off that list
    private func toggle(_ id: String) -> some View {
        let list = store.activeList
        let on = list?.ids.contains(id) ?? false
        let name = list?.name ?? "My airports"
        return Button {
            if on, let list { store.setOnList(id, list.id, false) } else { store.add(id) }
        } label: {
            Image(systemName: on ? "checkmark" : "plus")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(on ? EFB.green : EFB.cyan)
                .frame(width: 44, height: 44)
                .background(EFB.panel, in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.borderless)
        .accessibilityLabel(on ? "Remove \(id) from \(name)" : "Add \(id) to \(name)")
    }

    private func open(_ id: String) {
        if makeHome { return pick(id) }
        focused = false
        path.append(id)
    }

    private func pick(_ id: String) {
        if let id = AirportStore.normalize(id) { store.setHome(id) }
        dismiss()
    }

    /// return key: open the top result (or pick it as home)
    private func addTopResult() {
        if let first = results.first {
            open(first.id)
        } else if let id = AirportStore.normalize(query) {
            open(id)
        }
    }
}

private struct ResultRow: View {
    let apt: AirportInfo
    let counts: Counts?
    let indexLoaded: Bool

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
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                Text([apt.icao, apt.location.isEmpty ? nil : apt.location,
                      apt.type == "airport" ? nil : apt.type?.capitalized]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(.system(size: 12.5))
                    .foregroundStyle(EFB.dim)
                    .lineLimit(1)
                // under the name, not beside it: counts beside it cut names to "Santa Bar…"
                if indexLoaded, let counts, counts.total > 0 {
                    CountAnnunciators(counts: counts).padding(.top, 3)
                }
            }
            Spacer(minLength: 6)
            if indexLoaded, (counts?.total ?? 0) == 0 {
                // NO CHANGE as a glyph, so it doesn't take the name's width either
                Image(systemName: "checkmark.circle")
                    .font(.system(size: 15))
                    .foregroundStyle(EFB.green)
                    .accessibilityLabel("No change")
            }
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(EFB.panel, in: RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
    }
}
