IF OBJECT_ID('dbo.case_memory', 'U') IS NULL
CREATE TABLE dbo.case_memory (
    case_id    NVARCHAR(100) NOT NULL,
    mem_key    NVARCHAR(100) NOT NULL,
    mem_type   NVARCHAR(30)  NOT NULL,
    mem_value  NVARCHAR(MAX) NOT NULL,
    created_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    expires_at DATETIME2     NOT NULL,
    CONSTRAINT pk_case_memory PRIMARY KEY (case_id, mem_key, mem_type)
);
GO
IF OBJECT_ID('dbo.case_results', 'U') IS NULL
CREATE TABLE dbo.case_results (
    case_id    NVARCHAR(100) NOT NULL PRIMARY KEY,
    alert_id   NVARCHAR(100) NOT NULL,
    status     NVARCHAR(40)  NOT NULL,
    result     NVARCHAR(MAX) NOT NULL,
    updated_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
IF OBJECT_ID('dbo.case_approvals', 'U') IS NULL
CREATE TABLE dbo.case_approvals (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    case_id       NVARCHAR(100) NOT NULL,
    decision      NVARCHAR(20)  NOT NULL,
    approver      NVARCHAR(100) NOT NULL,
    approver_role NVARCHAR(50)  NOT NULL,
    comment       NVARCHAR(500) NULL,
    decided_at    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
