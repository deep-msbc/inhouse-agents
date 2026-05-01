import type { DashboardConfig } from "@msbc/config-ui";

export const UserList4Config: DashboardConfig = {
  title: "Users",
  hasSearch: true,
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
  filters: [
    { type: "date-range", name: "date", },
    {
      type: "select",
      options: [],
      api: {
        url: '/api/roles'
      },
      labelKey: "display_name",
      valueKey: "id", name: "role"
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
  tableProps: {
    tableId: "users-table",
    tableName: "Users",
    columnDefs: [
      {
        headerName: '',
        checkboxSelection: true,
        width: 70
      },
      { field: "name", headerName: "Name" },
      { field: "email", headerName: "Email" },
      { field: "status", headerName: "Status" },
    ],
    rowSelection: 'multiple',
    noRowsOverlayComponent: () => <div>No users found.</div>,
  },
  
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
};