# Hướng dẫn CPS API — Provisioning OpenStack lab

Tài liệu mô tả cách gọi CPS API (curl) để dựng stack lab: **domain → project → instance + SSH từ host**.

Luồng tham chiếu thiết kế: [`instance-provisioning.md`](../instance-provisioning.md).

**Base URL:** `http://127.0.0.1:8000`  
**Provider:** `openstack-hanoi-lab` (`019fa7a7-9f46-7e71-b6f6-28a7c6632222`)

| Connection | ID | Scope | Project OpenStack |
|---|---|---|---|
| SYSTEM (admin) | `019fa7a7-9f47-7ff8-87b7-7fdda20f61a0` | SYSTEM | admin |
| PROJECT (lab) | `019fa7a7-dc82-796d-949f-f5c862f64e30` | PROJECT | ttcntt-cloud / domain hanoi |

**Lab resource IDs (ví dụ):**

| Resource | ID |
|---|---|
| Domain hanoi | `af62d90df1044aa3b37dd56430d30021` |
| Network ttcntt-private | `9faaafee-0216-429e-a9e7-3b7b59fdacb6` |
| External net provider | `c50c4ecd-a053-408e-bd45-fa8954f09f4e` |
| SG ttcntt-default-sg | `611196bf-150c-4e4c-9ef0-caafa41d15f8` |
| Image ubuntu-24.04 | `28a8e975-fb44-4f4e-aefd-09025cf2aa6b` |
| Flavor m1.medium | `3` |

> **Lưu ý flavor:** Lab dùng `m1.medium` (4096 MiB RAM), **không có** `n1.medium`.

**Quy ước chung:**

- Mọi `POST` mutation bắt buộc header `Idempotency-Key`.
- Response async trả `202` + `operation.id`; poll `GET /api/v1/operations/{id}` đến terminal state.
- Script tự động: `deploy/scripts/run-cmp-dev-cps-e2e.sh`

---

## Luồng tổng quan

| Bước | API / Operation | Ghi chú |
|---|---|---|
| 0 | `GET /health/ready` | Preflight |
| 1 | `POST .../inventory-syncs` | Catalog flavor + image |
| 1b | `POST .../inventory-refreshes` | Network vào CPS inventory |
| 2 | `POST .../domains/create` | Adopt domain `hanoi` |
| 3 | `POST .../projects/create` | Tạo project `ttcntt` |
| 4 | `POST .../instances` | VM `cmp-dev` (ubuntu-24.04, m1.medium) |
| 5 | `POST .../network-operations` | Associate FIP (nếu bước 4 chưa gán) |
| 6 | SSH từ host | `ssh -i ~/.ssh/id_ed25519 ubuntu@<FIP>` |

---

## Bước 0 — Preflight

**Mục đích:** Xác nhận CPS sẵn sàng (DB + RabbitMQ).

```bash
curl -sS http://127.0.0.1:8000/health/ready | jq .
```

**Response mẫu:**

```json
{
  "status": "ok",
  "checks": {
    "database": { "status": "up" },
    "rabbitmq": { "status": "up" }
  }
}
```

---

## Bước 1 — Inventory sync (catalog flavor/image)

**Mục đích:** CPS cần inventory `catalog_approved=true` trước khi tạo VM. Endpoint đúng: **`/inventory-syncs`** (không phải `/inventory/collect`).

**Request:**

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-dc82-796d-949f-f5c862f64e30/inventory-syncs" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: cmp-dev-inv-v3' \
  -d '{"collections":["flavor","image"]}'
```

**Giải thích:**

- `collections`: chỉ sync flavor + image (nhanh, tránh kẹt QUEUED khi sync port).
- Header `Idempotency-Key`: bắt buộc, tránh duplicate operation.

**Response (202 Accepted):** trả `operation.id` → poll `GET /api/v1/operations/{id}` → **SUCCEEDED**.

**OpenStack verify (controller):**

```bash
openstack flavor show 3 -c properties
# cmp-catalog-approved='true'

openstack image show 28a8e975-fb44-4f4e-aefd-09025cf2aa6b -c properties
# cmp-catalog-approved='true'
```

---

## Bước 1b — Inventory refresh (network)

**Mục đích:** `POST /instances` kiểm tra network ID có trong inventory của connection. Sync full network+port dễ kẹt QUEUED; dùng refresh từng network.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-dc82-796d-949f-f5c862f64e30/inventory-refreshes" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: ref-net' \
  -d '{"resource_type":"network","provider_resource_id":"9faaafee-0216-429e-a9e7-3b7b59fdacb6"}'

curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-dc82-796d-949f-f5c862f64e30/inventory-refreshes" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: ref-ext' \
  -d '{"resource_type":"network","provider_resource_id":"c50c4ecd-a053-408e-bd45-fa8954f09f4e"}'
```

> Nếu bỏ qua bước này, `POST /instances` trả `PROVIDER_CONNECTION_NOT_FOUND` (network chưa có trong CPS DB).

---

## Bước 2 — Domain `hanoi` (adopt)

**Mục đích:** Domain `hanoi` đã tồn tại trên Keystone; CPS adopt qua lifecycle API với `provider_resource_id`.

**Connection:** SYSTEM (`019fa7a7-9f47-7ff8-87b7-7fdda20f61a0`)

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-9f47-7ff8-87b7-7fdda20f61a0/domains/create" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: cmp-dev-domain-v3' \
  -d '{
    "name": "hanoi",
    "provider_resource_id": "af62d90df1044aa3b37dd56430d30021",
    "description": "CMP domain hanoi"
  }'
```

**Response mẫu (SUCCEEDED):**

```json
{
  "state": "SUCCEEDED",
  "result_payload": {
    "resource": {
      "id": "<domain-id>",
      "name": "hanoi",
      "is_enabled": true,
      "description": "Hanoi region"
    }
  }
}
```

**OpenStack verify:**

```bash
openstack domain show hanoi -f value -c id -c name -c enabled
# af62d90df1044aa3b37dd56430d30021  hanoi  True
```

---

## Bước 3 — Project `ttcntt`

**Mục đích:** Tạo project tenant mới trong domain hanoi.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-9f47-7ff8-87b7-7fdda20f61a0/projects/create" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: cmp-dev-project-v3' \
  -d '{
    "name": "ttcntt",
    "domain_provider_resource_id": "af62d90df1044aa3b37dd56430d30021",
    "description": "CMP project ttcntt"
  }'
```

**Response mẫu (SUCCEEDED):**

```json
{
  "state": "SUCCEEDED",
  "result_payload": {
    "resource": {
      "id": "<project-id>",
      "name": "ttcntt",
      "domain_id": "<domain-id>",
      "description": "CMP project ttcntt"
    }
  }
}
```

**OpenStack verify:**

```bash
openstack project list --domain hanoi -f value -c ID -c Name
# 051b74024e18495cbc9255d7f8dbb2cc  ttcntt
# 1e4fc1809ea84392b29f81712e859813  ttcntt-cloud
```

> VM được tạo trên connection **ttcntt-cloud** (network lab shared), không phải project `ttcntt` mới — đúng thiết kế lab hiện tại.

---

## Bước 4 — Instance `cmp-dev`

**Mục đích:** Ubuntu 24.04, flavor m1.medium, network ttcntt-private, SG default, SSH key + floating IP.

**Connection:** PROJECT ttcntt-cloud (`019fa7a7-dc82-796d-949f-f5c862f64e30`)

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-dc82-796d-949f-f5c862f64e30/instances" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: cmp-dev-vm-v4' \
  -d '{
    "name": "cmp-dev",
    "flavor_provider_resource_id": "3",
    "boot_source": "IMAGE",
    "image_provider_resource_id": "28a8e975-fb44-4f4e-aefd-09025cf2aa6b",
    "network_provider_resource_ids": ["9faaafee-0216-429e-a9e7-3b7b59fdacb6"],
    "security_group_provider_resource_ids": ["611196bf-150c-4e4c-9ef0-caafa41d15f8"],
    "floating_network_provider_resource_id": "c50c4ecd-a053-408e-bd45-fa8954f09f4e",
    "ssh_public_key": "<~/.ssh/id_ed25519.pub>",
    "ssh_username": "ubuntu"
  }'
```

**Giải thích request body:**

| Field | Giá trị | Ý nghĩa |
|---|---|---|
| `flavor_provider_resource_id` | `3` | m1.medium (4096 MiB) |
| `image_provider_resource_id` | ubuntu-24.04 UUID | Boot từ Glance image |
| `network_provider_resource_ids` | ttcntt-private | Mạng tenant lab |
| `floating_network_provider_resource_id` | provider | Allocate FIP từ external net |
| `ssh_public_key` | ed25519 pub | Nova inject keypair |
| `ssh_username` | `ubuntu` | User SSH mặc định Ubuntu cloud image |

**Lỗi thường gặp:** operation **FAILED** (`PROVIDER_RESOURCE_NOT_FOUND`, compute) dù Nova đã **ACTIVE** — FIP allocate OK nhưng associate trong cùng handler fail. Xem bước 5.

**OpenStack verify:**

```bash
export OS_PROJECT_NAME=ttcntt-cloud OS_PROJECT_DOMAIN_NAME=hanoi
openstack server list --name cmp-dev
openstack floating ip list
```

---

## Bước 5 — Gán Floating IP (SSH từ host)

**Mục đích:** Associate FIP vào port VM — bắt buộc khi bước 4 chưa trả `access.ssh.host`.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8000/api/v1/provider-connections/019fa7a7-dc82-796d-949f-f5c862f64e30/network-operations" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: cmp-dev-fip-associate' \
  -d '{
    "resource_type": "floating-ip",
    "operation": "associate",
    "provider_resource_id": "<floating-ip-id>",
    "port_provider_resource_id": "<instance-port-id>"
  }'
```

**Giải thích:**

- `provider_resource_id`: ID floating IP trên Neutron (lấy từ `openstack floating ip list`).
- `port_provider_resource_id`: **bắt buộc** — port của VM (`openstack port list --server <server-id>`), không phải server ID.

**Response mẫu (SUCCEEDED):**

```json
{
  "state": "SUCCEEDED",
  "result_payload": {
    "resource": {
      "floating_ip_address": "192.168.0.246",
      "fixed_ip_address": "10.10.50.67",
      "port_id": "<port-id>"
    }
  }
}
```

---

## Bước 6 — SSH từ host

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@192.168.0.246
```

Lệnh đúng là **`ssh -i`**, không phải `sh -i`.

---

## Lưu ý vận hành

1. **Instance create atomicity:** FIP associate có thể cần gọi riêng (task CPS-1803 L4).
2. **Inventory sync kẹt QUEUED:** Tránh sync full `port`/`instance`; dùng flavor+image sync + network refresh.
3. **PROVIDER_CONNECTION_NOT_FOUND trên instance:** Refresh network trước `POST /instances`.
4. **Pre-requisite OpenStack admin:** Gắn `cmp-catalog-approved=true` trên flavor/image trước inventory sync.
