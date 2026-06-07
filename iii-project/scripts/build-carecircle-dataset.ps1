param(
  [string]$InputCsv = "C:\Users\soura\Downloads\Dataset.csv",
  [string]$OutputJson = "C:\Users\soura\OneDrive\Documents\iii\assets\carecircle-dataset.json"
)

$ErrorActionPreference = "Stop"
$rows = @(Import-Csv -LiteralPath $InputCsv)

$bloodMap = @{
  "O Positive" = "O+"; "O Negative" = "O-"; "A Positive" = "A+"; "A Negative" = "A-"
  "B Positive" = "B+"; "B Negative" = "B-"; "AB Positive" = "AB+"; "AB Negative" = "AB-"
}
$firstNames = @("Aarav","Diya","Kiran","Ishaan","Maya","Rohan","Neha","Vikram","Tara","Aditya","Leela","Nikhil","Priya","Siddharth","Amina","Kunal")
$lastNames = @("Sharma","Reddy","Patel","Nair","Singh","Das","Khan","Rao")
$conditions = @("Thalassemia Major","Sickle Cell Disease","Thalassemia Intermedia")

function Normalize-Blood([string]$value) {
  if ($bloodMap.ContainsKey($value)) { return $bloodMap[$value] }
  if ([string]::IsNullOrWhiteSpace($value)) { return "Unknown" }
  return $value
}
function To-Number($value, [double]$fallback = 0) {
  $parsed = 0.0
  if ([double]::TryParse([string]$value, [ref]$parsed)) { return $parsed }
  return $fallback
}
function To-Date($value) {
  if ([string]::IsNullOrWhiteSpace([string]$value)) { return $null }
  $parsed = [datetime]::MinValue
  if ([datetime]::TryParse([string]$value, [ref]$parsed)) { return $parsed.ToString("yyyy-MM-dd") }
  return $null
}
function Compatible([string]$donor, [string]$patient) {
  $map = @{
    "O-"=@("O-","O+","A-","A+","B-","B+","AB-","AB+"); "O+"=@("O+","A+","B+","AB+")
    "A-"=@("A-","A+","AB-","AB+"); "A+"=@("A+","AB+"); "B-"=@("B-","B+","AB-","AB+")
    "B+"=@("B+","AB+"); "AB-"=@("AB-","AB+"); "AB+"=@("AB+")
  }
  return $map.ContainsKey($donor) -and $map[$donor] -contains $patient
}
function Person-Name([int]$index, [string]$prefix = "") {
  $name = "$($firstNames[$index % $firstNames.Count]) $($lastNames[[math]::Floor($index / $firstNames.Count) % $lastNames.Count])"
  if ($prefix) { return "$prefix $name" }
  return $name
}

$donorRows = @($rows | Where-Object { $_.role -in @("Bridge Donor","Emergency Donor") })
$donorGroups = @($donorRows | Group-Object user_id)
$donors = @()
$donorIdBySource = @{}
for ($i = 0; $i -lt $donorGroups.Count; $i++) {
  $group = $donorGroups[$i]
  $row = @($group.Group | Sort-Object @{Expression={ if ($_.role -eq "Bridge Donor") { 1 } else { 0 } };Descending=$true})[0]
  $id = "DON-{0:D5}" -f ($i + 1)
  $donorIdBySource[$group.Name] = $id
  $donors += [ordered]@{
    id=$id; name=Person-Name $i; blood_group=Normalize-Blood $row.blood_group; gender=$row.gender
    latitude=To-Number $row.latitude 17.385; longitude=To-Number $row.longitude 78.4867
    donor_type=if ($row.donor_type) {$row.donor_type} else {$row.role}
    source_roles=@($group.Group.role | Sort-Object -Unique)
    last_contacted_date=To-Date $row.last_contacted_date; last_donation_date=To-Date $row.last_donation_date
    next_eligible_date=To-Date $row.next_eligible_date
    donations_till_date=[int](To-Number $row.donations_till_date 0)
    eligibility_status=if ($row.eligibility_status) {$row.eligibility_status} else {"unknown"}
    cycle_of_donations=[int](To-Number $row.cycle_of_donations 90)
    total_calls=[int](To-Number $row.total_calls 0)
    calls_to_donations_ratio=To-Number $row.calls_to_donations_ratio 0
    active_status=if ($row.user_donation_active_status) {$row.user_donation_active_status} else {"Unknown"}
    donated_earlier=([string]$row.donated_earlier).ToLower() -eq "true"
    inactive_reason=$row.inactive_trigger_comment; assigned_patients=@()
  }
}
$donorById = @{}
foreach ($donor in $donors) { $donorById[$donor.id] = $donor }

$volunteerGroups = @($rows | Where-Object role -eq "Volunteer" | Group-Object user_id)
$volunteers = @()
for ($i = 0; $i -lt $volunteerGroups.Count; $i++) {
  $row = $volunteerGroups[$i].Group[0]
  $volunteers += [ordered]@{
    id="VOL-{0:D3}" -f ($i + 1); name=Person-Name ($i + 5) "Volunteer"
    gender=$row.gender; latitude=To-Number $row.latitude 17.385; longitude=To-Number $row.longitude 78.4867
    active=($row.role_status -ne "false")
  }
}

$bridgeGroups = @($rows | Where-Object { $_.bridge_id } | Group-Object bridge_id | Sort-Object Name)
$patients = @()
for ($i = 0; $i -lt $bridgeGroups.Count; $i++) {
  $group = $bridgeGroups[$i]
  $patientRow = @($group.Group | Where-Object role -eq "Patient" | Select-Object -First 1)
  $sample = if ($patientRow.Count) { $patientRow[0] } else { $group.Group[0] }
  $patientId = "PAT-{0:D3}" -f ($i + 1)
  $patientBlood = Normalize-Blood $sample.bridge_blood_group
  if ($patientBlood -eq "Unknown") { $patientBlood = Normalize-Blood $sample.blood_group }

  $groupDonorIds = @($group.Group | Where-Object { $donorIdBySource.ContainsKey($_.user_id) } |
    ForEach-Object { $donorIdBySource[$_.user_id] } | Select-Object -Unique)
  $ranked = @($donors | Where-Object {
      Compatible $_.blood_group $patientBlood -and ($_.active_status -eq "Active" -or $_.eligibility_status -eq "eligible")
    } | Sort-Object @{Expression={
      $score = if ($groupDonorIds -contains $_.id) { 1000 } else { 0 }
      if ($_.eligibility_status -eq "eligible") { $score += 50 }
      if ($_.active_status -eq "Active") { $score += 30 }
      $score + [math]::Min(20, $_.donations_till_date * 3)
    };Descending=$true})
  $circle = @($ranked | Select-Object -First 8 | ForEach-Object id)
  foreach ($donorId in $circle) {
    if ($donorById[$donorId].assigned_patients -notcontains $patientId) {
      $donorById[$donorId].assigned_patients += $patientId
    }
  }
  $frequency = [int](To-Number $sample.frequency_in_days 21)
  if ($frequency -le 0) { $frequency = 21 }
  $patients += [ordered]@{
    id=$patientId; bridge_code="BRG-{0:D3}" -f ($i + 1); name=Person-Name ($i + 40) "Patient"
    blood_group=$patientBlood; gender=if ($sample.bridge_gender) {$sample.bridge_gender} else {$sample.gender}
    location="Hyderabad, Telangana"; latitude=To-Number $sample.latitude 17.385; longitude=To-Number $sample.longitude 78.4867
    condition=$conditions[$i % $conditions.Count]; quantity_required=[int](To-Number $sample.quantity_required 1)
    last_transfusion_date=To-Date $sample.last_transfusion_date; expected_next_date=To-Date $sample.expected_next_transfusion_date
    frequency_days=$frequency; primary_donors=@($circle | Select-Object -First 3)
    backup_donors=@($circle | Select-Object -Skip 3 -First 5)
    volunteers=@($volunteers | Select-Object -Skip (($i * 2) % [math]::Max(1,$volunteers.Count)) -First 2 | ForEach-Object id)
    coordinator="Coordinator {0:D2}" -f (($i % 12) + 1)
    escalation_path=@("Primary Circle","Backup Circle","Volunteer Lead","City Coordinator","Hyderabad Blood Bank Network")
    status_index=$i % 5
  }
}

$records = @()
for ($i = 0; $i -lt $rows.Count; $i++) {
  $row = $rows[$i]
  $entityId = if ($donorIdBySource.ContainsKey($row.user_id)) { $donorIdBySource[$row.user_id] } else { "USR-{0:D5}" -f ($i + 1) }
  $bridgeIndex = [array]::IndexOf(@($bridgeGroups.Name), $row.bridge_id)
  $records += [ordered]@{
    id="REC-{0:D5}" -f ($i + 1); entity_id=$entityId
    bridge_id=if ($bridgeIndex -ge 0) {"BRG-{0:D3}" -f ($bridgeIndex + 1)} else {$null}
    role=$row.role; role_status=$row.role_status; bridge_status=$row.bridge_status
    blood_group=Normalize-Blood $row.blood_group; gender=$row.gender
    latitude=To-Number $row.latitude 0; longitude=To-Number $row.longitude 0
    donor_type=$row.donor_type; eligibility_status=$row.eligibility_status
    active_status=$row.user_donation_active_status; status=$row.status
    registration_date=To-Date $row.registration_date; last_contacted_date=To-Date $row.last_contacted_date
    last_donation_date=To-Date $row.last_donation_date; donations_till_date=[int](To-Number $row.donations_till_date 0)
    total_calls=[int](To-Number $row.total_calls 0)
  }
}

$roleCounts = [ordered]@{}
$rows | Group-Object role | Sort-Object Name | ForEach-Object { $roleCounts[$_.Name] = $_.Count }
$output = [ordered]@{
  generated_at=(Get-Date).ToString("s"); source="Dataset.csv"
  source_summary=[ordered]@{
    total_records=$rows.Count; unique_users=@($rows.user_id | Sort-Object -Unique).Count
    bridge_donors=@($rows | Where-Object role -eq "Bridge Donor").Count
    emergency_donors=@($rows | Where-Object role -eq "Emergency Donor").Count
    volunteers=@($rows | Where-Object role -eq "Volunteer").Count
    patients=@($rows | Where-Object role -eq "Patient").Count
    guests=@($rows | Where-Object role -eq "Guest").Count
    unique_bridges=$bridgeGroups.Count
    active_donors=@($donorRows | Where-Object user_donation_active_status -eq "Active").Count
    inactive_donors=@($donorRows | Where-Object user_donation_active_status -eq "Inactive").Count
    role_counts=$roleCounts
  }
  patients=$patients; donors=$donors; volunteers=$volunteers; records=$records
}

$json = $output | ConvertTo-Json -Depth 9 -Compress
[System.IO.File]::WriteAllText($OutputJson, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output "Generated ${OutputJson}: $($records.Count) records, $($patients.Count) care circles, $($donors.Count) donors, $($volunteers.Count) volunteers."
