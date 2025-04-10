document.addEventListener('DOMContentLoaded', function() {
const filterButtons = document.querySelectorAll('.filter-buttons .btn');
const orderTableBody = document.querySelector('#order-table tbody');
const orderRows = orderTableBody ? Array.from(orderTableBody.querySelectorAll('tr')) : [];
if (!orderTableBody) {
    console.warn("Order table body not found. Filtering disabled.");
    return;
}
if(orderRows.length === 0) {
    console.info("No order rows found in the table.");
}

function parseDate(dateString) {
    if (!dateString) return null;
    try {
        const date = new Date(dateString);
        // Check if the date object is valid
        if (isNaN(date.getTime())) {
            console.warn(`Could not parse date: ${dateString} - Invalid Date`);
            return null;
        }
        return date;
    } catch (e) {
        console.warn(`Error parsing date: ${dateString}`, e);
        return null;
    }
}

function filterOrders(filterType) {
    const now = new Date();
    // Get the date part in UTC (year, month, day)
    const todayUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));

    let cutoffDateUTC = null;

    switch (filterType) {
        case 'day':
            cutoffDateUTC = new Date(todayUTC); // Beginning of today UTC
            break;
        case 'week':
            cutoffDateUTC = new Date(todayUTC);
            cutoffDateUTC.setUTCDate(todayUTC.getUTCDate() - 7);
            break;
        case 'month':
            // Get the first day of the current month in UTC
            cutoffDateUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
            break;
        case 'all':
        default:
            cutoffDateUTC = null;
            break;
    }

    let visibleRowCount = 0;
    orderRows.forEach(row => {
        const dateStr = row.dataset.date;
        const orderDate = parseDate(dateStr);

        let showRow = false;
        if (filterType === 'all' || !cutoffDateUTC) {
            showRow = true;
        } else if (orderDate) {
            // Convert orderDate to UTC for comparison
            const orderDateUTC = new Date(Date.UTC(orderDate.getFullYear(), orderDate.getMonth(), orderDate.getDate()));
            if (orderDateUTC >= cutoffDateUTC) {
                showRow = true;
            }
        }

        row.style.display = showRow ? '' : 'none';
        if (showRow) {
            visibleRowCount++;
        }
    });

    const noResultsRow = orderTableBody.querySelector('.no-results-message');
    if (visibleRowCount === 0 && orderRows.length > 0) {
        if (!noResultsRow) {
            const tr = document.createElement('tr');
            tr.className = 'no-results-message';
            const td = document.createElement('td');
            const numberOfColumns = orderTableBody.closest('table').querySelector('thead tr').childElementCount;
            td.colSpan = numberOfColumns;
            td.textContent = 'No orders match the selected filter.';
            td.style.textAlign = 'center';
            tr.appendChild(td);
            orderTableBody.appendChild(tr);
        } else {
            noResultsRow.style.display = '';
        }
    } else if (noResultsRow) {
        noResultsRow.style.display = 'none';
    }
}

filterButtons.forEach(button => {
    button.addEventListener('click', function() {
        filterButtons.forEach(btn => btn.classList.remove('active'));
        this.classList.add('active');
        const filterType = this.id.replace('filter-', '');
        filterOrders(filterType);
    });
});

const initiallyActiveButton = document.querySelector('.filter-buttons .btn.active') || document.getElementById('filter-all');
if (initiallyActiveButton) {
    initiallyActiveButton.click();
} else {
    filterOrders('all');
}
});