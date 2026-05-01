import type { DashboardConfig } from "@msbc/config-ui";
import Card from "../../../components/Card";
import { GridIcon, ListIcon } from "../../../assets/svg";

export const UserList5Config: DashboardConfig = {
  title: "Users",
  hasSearch: true,
  searchBarProps: {
    placeholder: "Search users...",
  },
  
  createButtonProps: {
    text: 'Add User',
    onClick: () => { }
  },
  actions: [
    {
      text: "Remove Users",
      api: {
        url: "/api/users",
        method: "post",
        autoFetch: false
      },
    },
    {
      text: "Disable Users",
      api: {
        url: "/api/users",
        method: "post",
        autoFetch: false
      }
    },
  ],

  // FILTERS
  filters: [
    {
      name: "role",
      type: "select",
      placeholder: "Select Role",
      options: [],
      api: {
        url: '/api/roles'
      },
      labelKey: 'display_name',
      valueKey: "id"
    },
    {
      name: "date",
      type: "date-range",
      startDateKey: "fromDate",
      endDateKey: "toDate",
      dateFormat: "yyyy-MM-dd",
    },
  ],

  api: {
    url: "/api/example",
    method: "get",
    params: {
      limit: 10
    }
  },
  apiResponseMapper: (data: any) => {
    return {
      data: []
    }
  },

  // Table 
  tableProps: {
    tableId: "user-table",
    tableName: "Users",
    columnDefs: [
      {
        headerName: '',
        checkboxSelection: true,
        width: 70
      },
      {
        field: "username",
        headerName: "Name",
        sortable: true,
        width: 250
      },
      {
        field: "email",
        headerName: "Email",
        width: 250
      },
      {
        field: "phone",
        headerName: "Contact no.",
        width: 220

      },
      {
        field: "Address",
        headerName: "Address Detail",
        width: 300
      },
      {
        field: "role",
        headerName: "Role",
        sortable: true,
      },
      {
        field: "createdAt",
        headerName: "Created At",
        sortable: true,
      },
    ],
    rowSelection: "multiple",
    noRowsOverlayComponent: () => <div>No users found.</div>
  },


  // LIST VIEW
  listProps: {
    CardComponent: Card,
    layout: { columns: 4, gap: "10px", cardWidth: "1fr", wrap: true },
    scrollHeight: "50px",
    minHeight : "100px",
    emptyComponent: "There are no records" 
   },

  modeSwitchProps: {
    offIcon: ListIcon,
    onIcon: GridIcon,
    activeColor: "var(--color-primary-07)",
    inactiveColor: "var(--color-gray-04)",
  },
  enableModeSwitch: true,

  // PAGINATION
  paginationParams: {
    pageIndex: "page",
    pageLimit: "limit",
  },

  // Advance Filters  
  advanceFilterProps: {
    hasAdvancedFilter: true,
    hasFilterButton: true,
    fieldInfo: [],
    fieldTypeInfo: {
      text: [{
        lookup_key: "",
        info: ""
      }],
      bool: [{
        lookup_key: "",
        info: ""
      }],
      date: [{
        lookup_key: "",
        info: ""
      }],
      int: [{
        lookup_key: "",
        info: ""
      }],
      phone: [{
        lookup_key: "",
        info: ""
      }]
    },
    filterTitle: 'Advance Filters',
    isModalOpen: false,
    onClose: () => { }
  }
}


