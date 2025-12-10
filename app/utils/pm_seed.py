"""
PM Checklists Seed Utility

Automatically populates PM checklists for a new company from the SFG20 XML file.
"""

import os
import xml.etree.ElementTree as ET
from html import unescape
import re
from typing import Dict, List
from collections import defaultdict
from sqlalchemy.orm import Session
import logging

from app.models import (
    PMEquipmentClass, PMSystemCode, PMAssetType,
    PMChecklist, PMActivity
)

logger = logging.getLogger(__name__)

# =============================================================================
# SIMPLIFIED 8-CLASS EQUIPMENT STRUCTURE
# =============================================================================

EQUIPMENT_CLASSES = {
    'HVAC': {
        'code': 'HVAC',
        'name': 'HVAC',
        'description': 'Heating, Ventilation, and Air Conditioning Systems',
        'sort_order': 1
    },
    'ELEC': {
        'code': 'ELEC',
        'name': 'Electrical',
        'description': 'Electrical Installations, Lighting, and Power Systems',
        'sort_order': 2
    },
    'PLUMB': {
        'code': 'PLUMB',
        'name': 'Plumbing & Water',
        'description': 'Water Supply, Drainage, and Sanitary Systems',
        'sort_order': 3
    },
    'FIRE': {
        'code': 'FIRE',
        'name': 'Fire & Safety',
        'description': 'Fire Protection, Alarms, and Safety Systems',
        'sort_order': 4
    },
    'BMS': {
        'code': 'BMS',
        'name': 'Building Management',
        'description': 'Building Management Systems, Controls, and Automation',
        'sort_order': 5
    },
    'SPEC': {
        'code': 'SPEC',
        'name': 'Specialist Systems',
        'description': 'Specialist Installations (Pools, Cold Rooms, etc.)',
        'sort_order': 6
    },
    'FUEL': {
        'code': 'FUEL',
        'name': 'Fuel Systems',
        'description': 'Fuel Storage and Distribution Systems',
        'sort_order': 7
    },
    'EXT': {
        'code': 'EXT',
        'name': 'External Works',
        'description': 'External Drainage and Building Fabric',
        'sort_order': 8
    }
}

# Mapping from system code keywords to Equipment Class
SYSTEM_CODE_MAPPING = {
    'HVAC': [
        'Air Handling', 'AHU', 'Heating', 'Cooling', 'Air Conditioning',
        'Heat Pump', 'Split System', 'Chiller', 'Boiler', 'Burner',
        'Heat Exchanger', 'Heat Emitter', 'Radiator', 'Fan Coil',
        'Terminal Unit', 'VAV', 'FCU', 'Condenser', 'Evaporator',
        'Compressor', 'Refriger', 'Fan', 'Ventilat', 'Ductwork',
        'Ducting', 'Damper', 'Grille', 'Diffuser', 'Louvre',
        'Belt Drive', 'Motor', 'Actuator', 'Humidifier', 'Dry Cooler',
        'Cooling Tower', 'Heat Recovery', 'Thermal Wheel', 'Flue',
        'Room Air Conditioner', 'Smoke Extract', 'Central Heating',
        'Central Cooling', 'Local Heating', 'Local Cooling',
        'Ventilation Ancillaries', 'Hose Reel'
    ],
    'ELEC': [
        'Electrical', 'Lighting', 'Emergency Light', 'Power', 'Generator',
        'UPS', 'Battery', 'Distribution Board', 'Switch', 'Starter',
        'Transformer', 'Cable', 'Conduit', 'Earthing', 'Bonding',
        'PDU', 'High Voltage', 'HV', 'Solar', 'Photovoltaic', 'PV',
        'Lightning Conductor', 'PAT', 'Portable Appliance', 'Isolator',
        'Fuse', 'Circuit', 'Mains', 'Sub-main', 'Hazardous Area'
    ],
    'PLUMB': [
        'Water', 'Plumbing', 'Sanitary', 'Drainage', 'Drain', 'Sewer',
        'Pump', 'Calorifier', 'Hot Water', 'Cold Water', 'Cylinder',
        'Tank', 'Cistern', 'Shower', 'Tap', 'Valve', 'Pipework',
        'Pipe', 'Macerator', 'Interceptor', 'Water Treatment',
        'Softener', 'UV Disinfect', 'Expansion Vessel', 'Pressuri',
        'Boosting', 'Ion Exchange', 'Rainwater', 'Gutter', 'Downpipe',
        'Steam', 'Condensate', 'Flash Steam'
    ],
    'FIRE': [
        'Fire Alarm', 'Fire Detection', 'Fire Extinguish', 'Sprinkler',
        'Fire Suppression', 'Gas Extinguish', 'Foam System', 'Hose Reel',
        'Hydrant', 'Rising Main', 'Smoke Detector', 'Heat Detector',
        'Gas Detection', 'CO2', 'Carbon Dioxide', 'Fire Protection',
        'Thermal Insulation'
    ],
    'BMS': [
        'BMS', 'Building Management', 'Control Panel', 'Controller',
        'Sensor', 'Thermostat', 'Transducer', 'Optimiser', 'Compensator',
        'Time Switch', 'Timer', 'Indicator', 'Display', 'Alarm Module',
        'Outstation', 'Communication', 'P.A.', 'Public Address',
        'Security', 'Intruder Alarm', 'CCTV', 'Access Control',
        'Pneumatic Relay', 'Level Controller', 'Speed Controller'
    ],
    'SPEC': [
        'Swimming Pool', 'Pool', 'Spa', 'Whirlpool', 'Hydrotherapy',
        'Cold Room', 'Refrigerated Display', 'Ice', 'Fountain',
        'Vacuum', 'Incinerator', 'Specialist', 'Food Storage',
        'Water Feature'
    ],
    'FUEL': [
        'Fuel', 'Oil Storage', 'Gas Storage', 'LPG', 'Petroleum',
        'Gas Booster', 'Fuel Distribution'
    ],
    'EXT': [
        'External', 'Barrier', 'Guardrail', 'Vehicle Access',
        'Sewage Treatment', 'Septic', 'Surface Water', 'Foul Water'
    ]
}

# Frequency code to days mapping
FREQUENCY_MAP = {
    '1W': {'name': 'Weekly', 'days': 7},
    '2W': {'name': 'Bi-Weekly', 'days': 14},
    '1M': {'name': 'Monthly', 'days': 30},
    '2M': {'name': 'Bi-Monthly', 'days': 60},
    '3M': {'name': 'Quarterly', 'days': 90},
    '4M': {'name': 'Tri-Annual', 'days': 120},
    '6M': {'name': 'Semi-Annual', 'days': 180},
    '12M': {'name': 'Annual', 'days': 365},
    '24M': {'name': 'Bi-Annual', 'days': 730},
    '36M': {'name': '3-Year', 'days': 1095},
    '48M': {'name': '4-Year', 'days': 1460},
    '60M': {'name': '5-Year', 'days': 1825},
    '0U': {'name': 'As Required', 'days': 0},
}


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_frequency(freq_code: str) -> tuple:
    """Parse frequency code and return (code, name, days)."""
    freq_code = freq_code.upper().strip()
    if freq_code in FREQUENCY_MAP:
        return (freq_code, FREQUENCY_MAP[freq_code]['name'], FREQUENCY_MAP[freq_code]['days'])
    return (freq_code, freq_code, 0)


def get_equipment_class_for_schedule(groups: List[str], title: str) -> str:
    """Determine the best Equipment Class for a schedule."""
    search_text = ' '.join(groups) + ' ' + title
    scores = defaultdict(int)

    for ec_key, keywords in SYSTEM_CODE_MAPPING.items():
        for keyword in keywords:
            if keyword.lower() in search_text.lower():
                scores[ec_key] += 1
                if re.search(rf'\b{re.escape(keyword)}\b', search_text, re.IGNORECASE):
                    scores[ec_key] += 1

    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]
    return 'HVAC'


def get_system_code_name(groups: List[str]) -> str:
    """Extract a clean system code name from schedule groups."""
    descriptive_groups = []
    for g in groups:
        if re.match(r'^[\d.]+\s', g):
            cleaned = re.sub(r'^[\d.]+\s*', '', g)
            if cleaned:
                descriptive_groups.append(cleaned)
        elif g.startswith('Sup List'):
            cleaned = re.sub(r'^Sup List\d+\s*', '', g)
            if cleaned:
                descriptive_groups.append(cleaned)
        else:
            descriptive_groups.append(g)

    if descriptive_groups:
        return descriptive_groups[-1]
    return groups[-1] if groups else 'General'


def parse_criticality(criticality: str) -> bool:
    """Determine if task is critical based on criticality level."""
    return criticality.lower() == 'red'


def parse_sfg20_xml(xml_path: str) -> List[dict]:
    """Parse SFG20 XML file and return list of schedules."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    schedules = []

    for schedule in root.findall('.//Schedule'):
        schedule_data = {
            'title': schedule.findtext('ScheduleTitle', ''),
            'reference': schedule.findtext('ScheduleReference', ''),
            'type': schedule.findtext('ScheduleType', ''),
            'date': schedule.findtext('ScheduleDate', ''),
            'version': schedule.findtext('ScheduleVersion', ''),
            'unit_of_measure': schedule.findtext('UnitOfMeasure', ''),
            'annual_timing': schedule.findtext('AnnualServiceTiming', ''),
            'groups': [],
            'introductions': [],
            'tasks': [],
            'service_timings': []
        }

        for group in schedule.findall('.//ScheduleGroup'):
            if group.text:
                schedule_data['groups'].append(group.text)

        for intro in schedule.findall('.//Introduction'):
            content = intro.findtext('Content', '')
            notes = intro.findtext('Notes', '')
            if content or notes:
                schedule_data['introductions'].append({
                    'content': clean_html(content),
                    'notes': clean_html(notes)
                })

        for task in schedule.findall('.//Task'):
            task_data = {
                'display_order': int(task.findtext('DisplayOrder', '0') or '0'),
                'item': clean_html(task.findtext('Item', '')),
                'criticality': task.findtext('Criticality', 'Amber'),
                'frequency': task.findtext('Frequency', '12M'),
                'action': clean_html(task.findtext('Action', '')),
                'notes': clean_html(task.findtext('Notes', '')),
                'skilling': task.findtext('Skilling', '')
            }
            schedule_data['tasks'].append(task_data)

        for timing in schedule.findall('.//ServiceTiming'):
            timing_data = {
                'criticality': timing.findtext('Criticality', ''),
                'frequency': timing.findtext('Frequency', ''),
                'minutes': int(timing.findtext('Minutes', '0') or '0')
            }
            schedule_data['service_timings'].append(timing_data)

        schedules.append(schedule_data)

    return schedules


def seed_pm_checklists_for_company(company_id: int, db: Session, xml_path: str = None) -> dict:
    """
    Seed PM checklists for a new company.

    Args:
        company_id: The company ID to seed data for
        db: Database session
        xml_path: Optional path to SFG20.xml. If not provided, uses default location.

    Returns:
        dict with statistics about what was created
    """
    # Default XML path relative to backend directory
    if xml_path is None:
        # Get the backend root directory (where misc/ folder is)
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        xml_path = os.path.join(backend_dir, 'misc', 'SFG20.xml')

    if not os.path.exists(xml_path):
        logger.warning(f"SFG20.xml not found at {xml_path}, skipping PM seed")
        return {'error': 'SFG20.xml not found'}

    logger.info(f"Seeding PM checklists for company {company_id}")

    # Parse XML
    schedules = parse_sfg20_xml(xml_path)

    # Track created entities
    equipment_classes: Dict[str, PMEquipmentClass] = {}
    system_codes: Dict[str, PMSystemCode] = {}

    stats = {
        'equipment_classes': 0,
        'system_codes': 0,
        'asset_types': 0,
        'checklists': 0,
        'activities': 0,
        'skipped_schedules': 0
    }

    try:
        # Create the 8 predefined equipment classes
        for ec_key, ec_config in EQUIPMENT_CLASSES.items():
            ec = PMEquipmentClass(
                company_id=company_id,
                code=ec_config['code'],
                name=ec_config['name'],
                description=ec_config['description'],
                sort_order=ec_config['sort_order'],
                is_active=True
            )
            db.add(ec)
            db.flush()
            equipment_classes[ec_key] = ec
            stats['equipment_classes'] += 1

        # Create system codes and asset types
        for schedule in schedules:
            if not schedule['tasks']:
                stats['skipped_schedules'] += 1
                continue

            # Determine equipment class
            ec_key = get_equipment_class_for_schedule(schedule['groups'], schedule['title'])
            ec = equipment_classes[ec_key]

            # Get clean system code name
            sc_name = get_system_code_name(schedule['groups'])

            # Create/get system code
            sc_key = f"{ec_key}:{sc_name.lower()}"
            if sc_key not in system_codes:
                sc = PMSystemCode(
                    equipment_class_id=ec.id,
                    code=f"{ec_key}-{len([k for k in system_codes if k.startswith(ec_key)]) + 1:03d}",
                    name=sc_name,
                    description="Imported from SFG20",
                    sort_order=len(system_codes),
                    is_active=True
                )
                db.add(sc)
                db.flush()
                system_codes[sc_key] = sc
                stats['system_codes'] += 1

            sc = system_codes[sc_key]

            # Create asset type
            description_parts = []
            for intro in schedule['introductions']:
                if intro['content']:
                    description_parts.append(intro['content'])

            asset_type = PMAssetType(
                system_code_id=sc.id,
                code=schedule['reference'],
                name=schedule['title'],
                pm_code=f"SFG-{schedule['reference']}",
                description=' '.join(description_parts)[:1000] if description_parts else None,
                sort_order=stats['asset_types'],
                is_active=True
            )
            db.add(asset_type)
            db.flush()
            stats['asset_types'] += 1

            # Group tasks by frequency
            tasks_by_frequency: Dict[str, List[dict]] = defaultdict(list)
            for task in schedule['tasks']:
                tasks_by_frequency[task['frequency']].append(task)

            # Get timing minutes
            timing_map = {}
            for timing in schedule['service_timings']:
                timing_map[timing['frequency']] = timing['minutes']

            # Create checklists and activities
            for freq_code, tasks in tasks_by_frequency.items():
                code, name, days = parse_frequency(freq_code)

                checklist = PMChecklist(
                    asset_type_id=asset_type.id,
                    frequency_code=code,
                    frequency_name=name,
                    frequency_days=days,
                    description=f"{schedule['title']} - {name} Maintenance",
                    is_active=True
                )
                db.add(checklist)
                db.flush()
                stats['checklists'] += 1

                # Create activities
                for task in tasks:
                    description = task['item']
                    if task['action']:
                        description = f"{task['item']}: {task['action']}"

                    est_minutes = timing_map.get(freq_code, None)

                    activity = PMActivity(
                        checklist_id=checklist.id,
                        sequence_order=task['display_order'],
                        description=description[:500],
                        estimated_duration_minutes=est_minutes,
                        requires_measurement=False,
                        measurement_unit=None,
                        is_critical=parse_criticality(task['criticality']),
                        safety_notes=task['notes'][:500] if task['notes'] else None,
                        is_active=True
                    )
                    db.add(activity)
                    stats['activities'] += 1

        db.flush()
        logger.info(f"PM seed completed for company {company_id}: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error seeding PM checklists for company {company_id}: {e}")
        raise
