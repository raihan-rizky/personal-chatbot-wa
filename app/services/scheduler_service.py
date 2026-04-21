"""Scheduler service for background tasks like random group roasting."""

import logging
import random
from app.services.whatsapp import get_groups, get_group_participants, send_message, get_profile_picture_url
from app.services.image_service import analyze_group_participant_roast, download_image

logger = logging.getLogger(__name__)

async def trigger_random_roast():
    """Serverless task to randomly roast a group participant once."""
    logger.info("Random Roast: Triggered serverless execution")
    try:
        groups = await get_groups()
        if not groups:
            logger.warning("Random Roast: No groups found")
            return {"status": "error", "message": "No groups found"}
            
        random_group = random.choice(groups)
        group_id = random_group.get("id")
        
        if not group_id:
            logger.warning("Random Roast: Selected group has no ID")
            return {"status": "error", "message": "Selected group has no ID"}
            
        participants = await get_group_participants(group_id)
        if not participants:
            logger.warning("Random Roast: No participants found in group %s", group_id)
            return {"status": "error", "message": "No participants found"}
            
        random_participant = random.choice(participants)
        
        chat_id = random_participant.get("phoneNumber")
        if not chat_id:
            chat_id = random_participant.get("id")
            
        if not chat_id:
            logger.warning("Random Roast: Selected participant has no known chat_id")
            return {"status": "error", "message": "Participant has no chat ID"}
            
        if "@s.whatsapp.net" in chat_id:
            chat_id = chat_id.replace("@s.whatsapp.net", "@c.us")
        elif "@lid" in chat_id:
            chat_id = chat_id.replace("@lid", "@c.us")
        
        logger.info("Random Roast: Selected group %s, participant %s", group_id, chat_id)
        
        pfp_url = await get_profile_picture_url(chat_id)
        pfp_bytes = await download_image(pfp_url) if pfp_url else None
        
        roast_msg = await analyze_group_participant_roast(pfp_bytes, chat_id)
        
        await send_message(group_id, roast_msg)
        logger.info("Random Roast: Successfully sent roast to group %s", group_id)
        return {"status": "success", "group_id": group_id, "chat_id": chat_id}
        
    except Exception as e:
        logger.exception("Random Roast Loop encountered an error: %s", str(e))
        return {"status": "error", "message": str(e)}
