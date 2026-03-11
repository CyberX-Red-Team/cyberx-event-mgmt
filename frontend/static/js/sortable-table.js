/**
 * SortableTable — reusable class for server-side sorted tables.
 *
 * Usage:
 *   1. Add data-sort-key="column_name" to sortable <th> elements.
 *   2. Instantiate:
 *        const sorter = new SortableTable({
 *            tableId: 'myTable',
 *            defaultSort: { column: 'created_at', order: 'desc' },
 *            onSort: (sortBy, sortOrder) => loadData(1)
 *        });
 *   3. In your load function, read sorter.getSort() to build the API URL.
 */
class SortableTable {
    constructor({ tableId, defaultSort, onSort }) {
        this.tableId = tableId;
        this.sortBy = defaultSort.column;
        this.sortOrder = defaultSort.order;
        this.onSort = onSort;
        this.disabled = false;
        this._init();
    }

    _init() {
        const table = document.getElementById(this.tableId);
        if (!table) return;
        const ths = table.querySelectorAll('thead th[data-sort-key]');
        ths.forEach(th => {
            th.style.cursor = 'pointer';
            th.style.userSelect = 'none';
            th.classList.add('sortable-header');
            const indicator = document.createElement('span');
            indicator.className = 'sort-indicator ms-1';
            th.appendChild(indicator);
            th.addEventListener('click', () => {
                if (!this.disabled) this._handleSort(th.dataset.sortKey);
            });
        });
        this._updateIndicators();
    }

    _handleSort(column) {
        if (this.sortBy === column) {
            this.sortOrder = this.sortOrder === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortBy = column;
            this.sortOrder = 'asc';
        }
        this._updateIndicators();
        this.onSort(this.sortBy, this.sortOrder);
    }

    _updateIndicators() {
        const table = document.getElementById(this.tableId);
        if (!table) return;
        table.querySelectorAll('thead th[data-sort-key]').forEach(th => {
            const indicator = th.querySelector('.sort-indicator');
            if (!indicator) return;
            const key = th.dataset.sortKey;
            if (this.disabled) {
                indicator.textContent = '\u21C5';
                th.classList.remove('sorted');
                th.style.cursor = 'default';
            } else if (key === this.sortBy) {
                indicator.textContent = this.sortOrder === 'asc' ? '\u25B2' : '\u25BC';
                th.classList.add('sorted');
                th.style.cursor = 'pointer';
            } else {
                indicator.textContent = '\u21C5';
                th.classList.remove('sorted');
                th.style.cursor = 'pointer';
            }
        });
    }

    getSort() {
        return { sortBy: this.sortBy, sortOrder: this.sortOrder };
    }

    setSort(column, order) {
        this.sortBy = column;
        this.sortOrder = order;
        this._updateIndicators();
    }

    setDisabled(disabled) {
        this.disabled = disabled;
        this._updateIndicators();
    }
}

/**
 * makeGroupsCollapsible — makes group header rows (tr.table-secondary)
 * clickable to collapse/expand the data rows beneath them.
 *
 * Call after rendering a grouped table body.
 *
 * @param {string} tbodyId - The id of the <tbody> element.
 */
function makeGroupsCollapsible(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    let currentHeader = null;

    Array.from(tbody.children).forEach(row => {
        if (row.classList.contains('table-secondary')) {
            currentHeader = row;
            currentHeader._groupRows = [];

            const td = row.querySelector('td');
            if (!td) return;

            // Insert chevron before existing content
            const chevron = document.createElement('span');
            chevron.className = 'group-chevron';
            chevron.textContent = '\u25BE'; // ▾
            td.insertBefore(chevron, td.firstChild);

            row.classList.add('group-header');
            row.addEventListener('click', function () {
                const collapsed = this.classList.toggle('group-collapsed');
                this._groupRows.forEach(r => r.style.display = collapsed ? 'none' : '');
            });
        } else if (currentHeader) {
            currentHeader._groupRows.push(row);
        }
    });
}
